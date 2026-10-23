import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import emulators
import build_package
import publish_v3
import restore_snapshot


def nds_bytes(size=520):
    data = bytearray(size)
    struct.pack_into("<IIII", data, 0x20, 512, 0x02000000, 0x02000000, 4)
    struct.pack_into("<IIII", data, 0x30, 516, 0x03800000, 0x03800000, 4)
    return bytes(data)


class V3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "work"
        self.upstream = self.workspace / "upstream"
        self.upstream.mkdir(parents=True)
        (self.upstream / "README.md").write_text("fixture source\n")
        (self.upstream / "LICENSE").write_text("license fixture\n")
        self.output = self.root / "bundle"
        self.spec = emulators.read_spec(ROOT / "packages/v3/gameyob.json")
        (self.upstream / "gameyob.nds").write_bytes(nds_bytes())

    def test_all_pinned_specs_are_valid(self):
        specs = emulators.load_specs(ROOT / "packages/v3")
        self.assertEqual([spec["id"] for spec in specs], list(emulators.PACKAGE_ORDER))
        self.assertTrue(next(spec for spec in specs if spec["id"] == "snemulds-06d")["manual"])

    def test_snemulds_06a_compatibility_sources_are_local(self):
        compat = ROOT / "packages/v3/compat/snemulds-06a"
        self.assertEqual({path.name for path in compat.glob("*.s")},
                         {"ds_arm7_crt0.s", "ds_arm9_crt0.s"})
        self.assertFalse(any(path.is_symlink() for path in compat.iterdir()))
        spec = emulators.read_spec(ROOT / "packages/v3/snemulds-06a.json")
        self.assertTrue(any("$DUSTY_PACKAGE_ROOT/packages/v3/compat/snemulds-06a/" in command
                            for command in spec["build"]["commands"]))

    def test_container_build_uses_pinned_image_and_prepares_legacy_inputs(self):
        spec = emulators.read_spec(ROOT / "packages/v3/snemulds-06a.json")
        names = {"ds_arm7_snemulds.ld", "ds_arm7_snemulds.specs",
                 "ds_arm9_snemulds.ld", "ds_arm9_snemulds.specs"}
        with zipfile.ZipFile(self.upstream / "linker_files.zip", "w") as archive:
            for name in sorted(names):
                archive.writestr(name, "linker fixture\n")
        with mock.patch.object(build_package, "git_output", return_value=spec["commit"]), \
                mock.patch.object(build_package.subprocess, "run") as execute:
            build_package.run(spec, self.workspace, container=True)
        args, kwargs = execute.call_args
        self.assertEqual(args[0][:4], ["docker", "run", "--rm", "-i"])
        self.assertIn(spec["toolchainImage"], args[0])
        self.assertIn(f"type=bind,source={ROOT},target=/builder,readonly", args[0])
        self.assertIn("DUSTY_PACKAGE_ROOT=/builder", args[0])
        self.assertEqual(kwargs["input"], "\n".join(spec["build"]["commands"]) + "\n")
        prepared = self.upstream / ".dusty-build/linker-files"
        self.assertEqual({path.name for path in prepared.iterdir()}, names)
        self.assertTrue(all(path.read_text() == "linker fixture\n" for path in prepared.iterdir()))

    def test_legacy_linker_archive_rejects_traversal_duplicates_and_symlinks(self):
        spec = emulators.read_spec(ROOT / "packages/v3/snemulds-06a.json")
        names = ["ds_arm7_snemulds.ld", "ds_arm7_snemulds.specs",
                 "ds_arm9_snemulds.ld", "ds_arm9_snemulds.specs"]
        for defect in ("traversal", "duplicate", "symlink"):
            with self.subTest(defect=defect):
                with zipfile.ZipFile(self.upstream / "linker_files.zip", "w") as archive:
                    for index, name in enumerate(names):
                        if index == 0 and defect == "traversal":
                            name = "../../escape"
                        elif index == 0 and defect == "duplicate":
                            name = names[1]
                        entry = zipfile.ZipInfo(name)
                        if index == 0 and defect == "symlink":
                            entry.external_attr = 0o120777 << 16
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore", UserWarning)
                            archive.writestr(entry, "fixture")
                with self.assertRaises(ValueError):
                    build_package.prepare_inputs(spec, self.upstream)
                self.assertFalse((self.upstream / ".dusty-build").exists())

    def test_gbarunner3_config_check_runs_on_host_after_compilation(self):
        spec = emulators.read_spec(ROOT / "packages/v3/gbarunner3.json")
        (self.upstream / spec["pinnedSubmodule"]["path"]).mkdir(parents=True)
        with mock.patch.object(build_package, "git_output", side_effect=[
                spec["commit"], spec["pinnedSubmodule"]["commit"]]), \
                mock.patch.object(build_package.subprocess, "run") as execute:
            build_package.run(spec, self.workspace, container=True)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args.args[0],
                         ["git", "-C", str(self.upstream), "diff", "--exit-code", "--", "configs"])

    def test_floating_pins_and_descriptor_drift_rejected(self):
        base = json.loads((ROOT / "packages/v3/gameyob.json").read_text())
        for key, value in (("commit", "main"), ("toolchainImage", "skylyrac/blocksds:latest"),
                           ("extensions", ["gb"]), ("manual", True), ("qualification", "qualified"),
                           ("revision", 0), ("revision", True), ("revision", 1.5), ("revision", 1000)):
            with self.subTest(key=key):
                spec = copy.deepcopy(base)
                spec[key] = value
                path = self.root / "spec.json"
                path.write_text(json.dumps(spec))
                with self.assertRaises(ValueError):
                    emulators.read_spec(path)

    def test_prebuilt_recipe_cannot_run_commands(self):
        path = ROOT / "packages/v3/snemulds-06d.json"
        spec = json.loads(path.read_text())
        spec["build"]["commands"] = ["make"]
        candidate = self.root / "spec.json"
        candidate.write_text(json.dumps(spec))
        with self.assertRaises(ValueError):
            emulators.read_spec(candidate)

    def test_bundle_is_deterministic_and_has_source_archive(self):
        manifest = emulators.bundle(self.spec, self.workspace, self.output)
        archive = self.output / "GameYob-c4d8672806b4a1cff8012fd40de4acf69b0094c2.zip"
        first = archive.read_bytes()
        self.assertEqual(manifest["format"], "dustymenu-build-bundle-v2")
        self.assertEqual(manifest["provenance"], "source")
        self.assertEqual(manifest["revision"], 3)
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(package.namelist(), ["emulators/gameyob.nds"])
            self.assertEqual(package.read("emulators/gameyob.nds"), nds_bytes())
        with tarfile.open(self.output / "source.tar.gz") as source:
            names = source.getnames()
            self.assertIn("upstream/README.md", names)
            self.assertNotIn("upstream/.git/config", names)
        emulators.bundle(self.spec, self.workspace, self.output)
        self.assertEqual(archive.read_bytes(), first)

    def test_bundle_rejects_symlink_and_wrong_destination(self):
        (self.upstream / "gameyob.nds").unlink()
        (self.upstream / "gameyob.nds").symlink_to(self.upstream / "README.md")
        with self.assertRaises(ValueError):
            emulators.bundle(self.spec, self.workspace, self.output)
        (self.upstream / "gameyob.nds").unlink()
        (self.upstream / "gameyob.nds").write_bytes(nds_bytes())
        spec = copy.deepcopy(self.spec)
        spec["build"]["outputs"][0]["destination"] = "/emulators/other.nds"
        with self.assertRaises(ValueError):
            emulators.bundle(spec, self.workspace, self.output)

    def test_package_revision_rejects_old_bundle_and_retains_legacy_compatibility(self):
        manifest = emulators.bundle(self.spec, self.workspace, self.output)
        for revision in (None, 1, 2, True, "3"):
            candidate = copy.deepcopy(manifest)
            if revision is None:
                candidate.pop("revision")
            else:
                candidate["revision"] = revision
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                publish_v3.package_assets(self.spec, self.output, candidate, self.root / "site")
        legacy = copy.deepcopy(self.spec)
        legacy.pop("revision")
        old_manifest = emulators.bundle(legacy, self.workspace, self.output)
        old_manifest.pop("revision") # Bundles produced before revision support.
        package = publish_v3.package_assets(legacy, self.output, old_manifest, self.root / "legacy-site")
        self.assertEqual(package["version"], legacy["commit"][:12] + "-dev")

    def test_publish_schema3_catalog_payload_and_signature(self):
        emulators.bundle(self.spec, self.workspace, self.output)
        bundles = self.root / "bundles"
        bundles.mkdir()
        target = bundles / "artifact"
        target.mkdir()
        for path in self.output.iterdir():
            (target / path.name).write_bytes(path.read_bytes())
        key = self.root / "publisher.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                       check=True, capture_output=True)
        public = publish_v3.public_key(key)
        site = self.root / "site"
        site.mkdir()
        (site / "index.html").write_text("site")
        (site / "health.json").write_text('{"service":"dustymenu-packages","status":"online"}')
        catalog = publish_v3.publish([self.spec], bundles, site, key, 1, public)
        raw = (site / "v3/catalog.bin").read_bytes()
        self.assertEqual(json.loads(raw[64:]), catalog)
        self.assertEqual(catalog["schema"], 3)
        package = catalog["packages"][0]
        self.assertEqual(package["version"], self.spec["commit"][:12] + "-dev-r3")
        self.assertEqual(package["extensions"], ["gb", "gbc", "sgb"])
        self.assertFalse(package["manual"])
        manifest_bytes = (site / "v3" / package["source"]).read_bytes()
        self.assertEqual(hashlib.sha512(manifest_bytes).hexdigest(), package["sha512"])
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["schema"], 3)
        payload = (site / "v3" / manifest["payload"]["source"]).read_bytes()
        self.assertEqual(hashlib.sha512(payload).hexdigest(), manifest["payload"]["sha512"])
        offset = 0
        for entry in manifest["files"]:
            data = payload[offset:offset + entry["size"]]
            offset += len(data)
            self.assertEqual(hashlib.sha512(data).hexdigest(), entry["sha512"])
        self.assertEqual(offset, package["totalSize"])
        self.assertTrue(any(entry["role"] == "license" for entry in manifest["files"]))
        (self.root / "catalog").write_bytes(raw[64:])
        (self.root / "sig").write_bytes(raw[:64])
        subprocess.run(["openssl", "pkey", "-pubout", "-in", str(key), "-out", str(self.root / "public.pem")],
                       check=True, capture_output=True)
        subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
                        "-inkey", str(self.root / "public.pem"), "-in", str(self.root / "catalog"),
                        "-sigfile", str(self.root / "sig")], check=True, capture_output=True)
        with self.assertRaises(ValueError):
            publish_v3.publish([self.spec], bundles, site, key, 1, public)
        with self.assertRaises(ValueError):
            publish_v3.publish([self.spec], bundles, site, key, 2, "00" * 32)
        snapshot = self.root / "snapshot.tar.gz"
        with tarfile.open(snapshot, "w:gz") as archive:
            archive.add(site, arcname=".")
        restored = self.root / "restored"
        restored.mkdir()
        (restored / "index.html").write_text("current site")
        (restored / "health.json").write_bytes((site / "health.json").read_bytes())
        restore_snapshot.restore(snapshot, restored)
        self.assertEqual((restored / "v3/catalog.bin").read_bytes(), raw)
        self.assertEqual((restored / "v3" / manifest["payload"]["source"]).read_bytes(), payload)
        with self.assertRaises(ValueError):
            publish_v3.publish([self.spec], bundles, restored, key, 1, public)
        publish_v3.publish([self.spec], bundles, restored, key, 2, public)
        self.assertEqual((restored / "index.html").read_text(), "current site")
        publish_v3.publish([self.spec], bundles, site, key, 2, public)


if __name__ == "__main__":
    unittest.main()
