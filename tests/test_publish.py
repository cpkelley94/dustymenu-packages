import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile
import warnings
import io
import tarfile

import test_packages as fixtures
ROOT, packages = fixtures.ROOT, fixtures.packages
sys.path.insert(0, str(ROOT / "tools"))
import publish
import restore_snapshot


class PublishTests(unittest.TestCase):
    def setUp(self):
        fixtures.PackageTests.setUp(self)
        self.key = self.root / "publisher.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(self.key)], check=True, capture_output=True)
        self.public = publish.public_key(self.key)
        self.site = self.root / "site"
        self.site.mkdir()
        (self.site / "index.html").write_text("Test site")
        (self.site / "health.json").write_text('{"service":"dustymenu-packages","status":"online"}')
        self.sources = self.root / "sources.tar.gz"
        self.sources.write_bytes(b"source archive fixture")
        packages.bundle(self.spec, self.source, self.output)

    def publish(self, sequence=1):
        return publish.publish(self.spec, self.output, self.site, self.key, self.sources, sequence, self.public)

    def test_signed_envelope_and_stream_layout(self):
        catalog = self.publish()
        raw = (self.site / "v2/catalog.bin").read_bytes()
        self.assertEqual(json.loads(raw[64:]), catalog)
        (self.root / "catalog").write_bytes(raw[64:]); (self.root / "sig").write_bytes(raw[:64])
        subprocess.run(["openssl", "pkey", "-in", str(self.key), "-pubout", "-out", str(self.root / "public.pem")], check=True, capture_output=True)
        subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(self.root / "public.pem"),
                        "-in", str(self.root / "catalog"), "-sigfile", str(self.root / "sig")], check=True, capture_output=True)
        package = catalog["packages"][0]
        manifest_bytes = (self.site / "v2" / package["source"]).read_bytes()
        self.assertEqual(hashlib.sha512(manifest_bytes).hexdigest(), package["sha512"])
        manifest = json.loads(manifest_bytes)
        payload = (self.site / "v2" / manifest["payload"]["source"]).read_bytes()
        self.assertEqual(hashlib.sha512(payload).hexdigest(), manifest["payload"]["sha512"])
        offset = 0
        for entry in manifest["files"]:
            data = payload[offset:offset + entry["size"]]; offset += len(data)
            self.assertEqual(hashlib.sha512(data).hexdigest(), entry["sha512"])
        self.assertEqual(offset, package["totalSize"])
        self.assertEqual(package["extensions"], ["gba", "agb"])
        self.assertLess(len(raw), 32832)

    def test_rollback_and_wrong_publisher_rejected(self):
        self.publish()
        with self.assertRaises(ValueError): self.publish()
        with self.assertRaises(ValueError):
            publish.publish(self.spec, self.output, self.site, self.key, self.sources, 2, "00" * 32)
        self.publish(2)

    def test_tampered_inventory_or_payload_rejected(self):
        inventory = self.output / "manifest.json"
        data = json.loads(inventory.read_text()); data["files"][0]["sha512"] = "0" * 128
        inventory.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.publish()

    def test_complete_301_configs_fit_the_manifest(self):
        for file in (self.source / "configs").iterdir(): file.unlink()
        for index in range(301): (self.source / f"configs/A{index:05}.json").write_text('{"runSettings":{}}')
        self.spec["expectedConfigs"] = 301
        packages.bundle(self.spec, self.source, self.output)
        catalog = self.publish()
        manifest = (self.site / "v2" / catalog["packages"][0]["source"]).read_bytes()
        self.assertEqual(len(json.loads(manifest)["files"]), 303)
        self.assertLess(len(manifest), 256 * 1024)

    def test_duplicate_zip_entry_rejected(self):
        archive = next(self.output.glob("*.zip"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "a") as zipped: zipped.writestr("GBARunner3.nds", b"bad")
        with self.assertRaises(ValueError): self.publish()

    def test_snapshot_restore_preserves_current_static_site(self):
        archive=self.root / "snapshot.tar.gz"
        with tarfile.open(archive,"w:gz") as package:
            for name,data in (("./index.html",b"old site"),("./v2/retained.pkg",b"payload"),
                              ("./v3/catalog.bin",b"signed catalog"),
                              ("./v3/releases/gameyob/retained.pkg",b"v3 payload")):
                item=tarfile.TarInfo(name);item.size=len(data);package.addfile(item,io.BytesIO(data))
        restore_snapshot.restore(archive,self.site)
        self.assertEqual((self.site / "index.html").read_text(),"Test site")
        self.assertEqual((self.site / "v2/retained.pkg").read_bytes(),b"payload")
        self.assertEqual((self.site / "v3/catalog.bin").read_bytes(),b"signed catalog")
        self.assertEqual((self.site / "v3/releases/gameyob/retained.pkg").read_bytes(),b"v3 payload")

    def test_snapshot_traversal_and_symlinks_rejected(self):
        for name,link in (("../tools/publish.py",False),("./v2/link",True),("./v3/link",True)):
            archive=self.root / "unsafe.tar.gz"
            with tarfile.open(archive,"w:gz") as package:
                item=tarfile.TarInfo(name)
                if link: item.type=tarfile.SYMTYPE;item.linkname="../../.private"
                package.addfile(item)
            with self.assertRaises(ValueError): restore_snapshot.restore(archive,self.site)


if __name__ == "__main__": unittest.main()
