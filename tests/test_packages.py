import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULE = importlib.util.spec_from_file_location("packages", ROOT / "tools/packages.py")
packages = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(packages)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input"
        self.output = self.root / "output"
        self.spec = packages.read_spec(ROOT / "packages/gbarunner3.json")
        self.spec["expectedConfigs"] = 2
        self.source.mkdir()
        self.binary = self.source / "code/bootstrap/GBARunner3.nds"
        self.binary.parent.mkdir(parents=True)
        nds = bytearray(520)
        struct.pack_into("<IIII", nds, 0x20, 512, 0x02000000, 0x02000000, 4)
        struct.pack_into("<IIII", nds, 0x30, 516, 0x03800000, 0x03800000, 4)
        self.binary.write_bytes(nds)
        (self.source / "configs").mkdir()
        (self.source / "configs/ABCD00.json").write_text('{"runSettings":{}}')
        (self.source / "configs/EFGH00.json").write_text('{"runSettings":{"test":true}}')
        (self.source / "source-commit.txt").write_text(self.spec["commit"] + "\n")
        (self.source / "libtwl-commit.txt").write_text(self.spec["libtwlCommit"] + "\n")

    def build(self):
        return packages.bundle(self.spec, self.source, self.output)

    def test_bundle_preserves_layout_hashes_and_is_deterministic(self):
        manifest = self.build()
        self.assertEqual(manifest["qualification"], "pending")
        archive = next(self.output.glob("*.zip"))
        original = archive.read_bytes()
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(set(package.namelist()), {"GBARunner3.nds", "_gba/configs/ABCD00.json", "_gba/configs/EFGH00.json"})
            for entry in manifest["files"]:
                data = package.read(entry["path"])
                self.assertEqual(len(data), entry["size"])
                self.assertEqual(hashlib.sha512(data).hexdigest(), entry["sha512"])
        self.build()
        self.assertEqual(archive.read_bytes(), original)
        for line in (self.output / "SHA256SUMS").read_text().splitlines():
            digest, filename = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256((self.output / filename).read_bytes()).hexdigest())

    def test_complete_301_config_inventory(self):
        for path in (self.source / "configs").iterdir():
            path.unlink()
        for index in range(301):
            (self.source / f"configs/A{index:05}.json").write_text('{"runSettings":{}}')
        self.spec["expectedConfigs"] = 301
        manifest = self.build()
        self.assertEqual(len(manifest["files"]), 302)
        self.assertGreater((self.output / "manifest.json").stat().st_size, 32768)
        self.assertLess((self.output / "manifest.json").stat().st_size, packages.MAX_MANIFEST)

    def test_wrong_provenance_rejected(self):
        (self.source / "libtwl-commit.txt").write_text("0" * 40)
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_config_is_not_silently_published(self):
        (self.source / "configs/ABCD00.json").unlink()
        with self.assertRaises(ValueError):
            self.build()

    def test_invalid_config_rejected(self):
        for content in ("not json", "[]"):
            with self.subTest(content=content):
                (self.source / "configs/ABCD00.json").write_text(content)
                with self.assertRaises(ValueError):
                    self.build()

    def test_symlink_rejected(self):
        config = self.source / "configs/ABCD00.json"
        config.unlink()
        config.symlink_to(self.source / "configs/EFGH00.json")
        with self.assertRaises(ValueError):
            self.build()

    def test_truncated_or_out_of_bounds_nds_rejected(self):
        self.binary.write_bytes(b"not an executable")
        with self.assertRaises(ValueError):
            self.build()
        nds = bytearray(512)
        struct.pack_into("<IIII", nds, 0x20, 512, 0x02000000, 0x02000000, 1024)
        self.binary.write_bytes(nds)
        with self.assertRaises(ValueError):
            self.build()

    def test_output_cannot_contaminate_input(self):
        with self.assertRaises(ValueError):
            packages.bundle(self.spec, self.source, self.source / "out")

    def test_floating_pins_and_qualified_flag_rejected(self):
        for key, value in (("commit", "develop"), ("toolchainImage", "devkitpro/devkitarm:latest"), ("qualification", "qualified")):
            with self.subTest(key=key):
                spec = copy.deepcopy(self.spec)
                spec[key] = value
                path = self.root / "spec.json"
                path.write_text(json.dumps(spec))
                with self.assertRaises(ValueError):
                    packages.read_spec(path)

    def test_site_validation(self):
        packages.check_site(ROOT / "public")
        site = self.root / "site"
        site.mkdir()
        (site / "index.html").write_text("site")
        (site / "health.json").write_text('{"service":"dustymenu-packages","status":"online"}')
        packages.check_site(site)
        with (site / "huge.nds").open("wb") as asset:
            asset.truncate(25 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            packages.check_site(site)


if __name__ == "__main__":
    unittest.main()
