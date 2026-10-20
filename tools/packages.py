#!/usr/bin/env python3
"""Validate build pins, assemble a GBARunner3 qualification bundle, check static assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILES = 512
MAX_MANIFEST = 256 * 1024


def read_spec(path):
    spec = json.loads(Path(path).read_text())
    if spec.get("id") != "gbarunner3" or spec.get("repository") != "Gericom/GBARunner3":
        raise ValueError("Unexpected package/repository")
    for field in ("commit", "libtwlCommit"):
        if not re.fullmatch(r"[0-9a-f]{40}", spec.get(field, "")):
            raise ValueError(f"{field} must be a full pinned commit")
    if not re.fullmatch(r"devkitpro/devkitarm:[0-9]{8}@sha256:[0-9a-f]{64}", spec.get("toolchainImage", "")):
        raise ValueError("Toolchain must be pinned by digest")
    count = spec.get("expectedConfigs")
    if type(count) is not int or not 1 <= count < MAX_FILES:
        raise ValueError("Invalid config count")
    if spec.get("qualification") != "pending":
        raise ValueError("This tool only produces pending qualification artifacts")
    return spec


def checked_file(path, root):
    # Follow no symlinks, including parent directories in the supplied input tree.
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError(f"Symlink in input: {item}")
        if item == root:
            break
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE:
        raise ValueError(f"Missing, empty, or oversized input: {path}")
    return path.read_bytes()


def check_nds(data):
    if len(data) < 512:
        raise ValueError("NDS header is truncated")
    ranges = []
    for header in (0x20, 0x30):
        offset, entry, address, size = struct.unpack_from("<IIII", data, header)
        if offset < 512 or not entry or not address or not size or offset + size > len(data):
            raise ValueError("Invalid ARM load section in NDS")
        ranges.append((offset, offset + size))
    if max(ranges[0][0], ranges[1][0]) < min(ranges[0][1], ranges[1][1]):
        raise ValueError("Overlapping ARM load sections")


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def bundle(spec, source, output):
    source = Path(source).absolute()
    output = Path(output)
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Output must be outside the input tree")
    for filename, expected in (("source-commit.txt", spec["commit"]), ("libtwl-commit.txt", spec["libtwlCommit"])):
        if checked_file(source / filename, source).decode().strip() != expected:
            raise ValueError(f"Build provenance does not match {filename}")
    executable = checked_file(source / "code/bootstrap/GBARunner3.nds", source)
    check_nds(executable)
    config_dir = source / "configs"
    if config_dir.is_symlink() or not config_dir.is_dir():
        raise ValueError("Missing configuration directory")
    configs = sorted(config_dir.iterdir())
    if len(configs) != spec["expectedConfigs"]:
        raise ValueError("Configuration count differs from the pinned source inventory")
    files = [("GBARunner3.nds", executable, "executable")]
    for path in configs:
        if not re.fullmatch(r"[A-Z0-9]{6}\.json", path.name):
            raise ValueError(f"Unexpected configuration path: {path.name}")
        data = checked_file(path, source)
        if not isinstance(json.loads(data), dict):
            raise ValueError(f"Configuration is not an object: {path.name}")
        files.append((f"_gba/configs/{path.name}", data, "compatibility-config"))
    if len(files) > MAX_FILES or sum(len(data) for _, data, _ in files) > MAX_TOTAL:
        raise ValueError("Package exceeds inventory/size limits")
    manifest = {
        "format": "dustymenu-build-bundle-v1",
        "id": spec["id"], "system": spec["system"], "qualification": "pending",
        "upstream": {key: spec[key] for key in ("repository", "commit", "libtwlCommit", "toolchainImage")},
        "files": [{"path": name, "size": len(data), "sha512": hashlib.sha512(data).hexdigest(), "role": role}
                  for name, data, role in files],
    }
    raw_manifest = json_bytes(manifest)
    if len(raw_manifest) > MAX_MANIFEST:
        raise ValueError("Manifest exceeds the 256 KiB limit")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"GBARunner3-{spec['commit']}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data, _ in files:
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, data)
    (output / "manifest.json").write_bytes(raw_manifest)
    sums = []
    for path in (archive, output / "manifest.json"):
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    (output / "SHA256SUMS").write_text("".join(sums))
    return manifest


def check_site(site):
    site = Path(site)
    if site.is_symlink() or not site.is_dir():
        raise ValueError("Missing static site directory")
    files = 0
    for path in site.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink in site: {path}")
        if path.is_file():
            files += 1
            if path.stat().st_size > 25 * 1024 * 1024:
                raise ValueError(f"Asset exceeds Pages' file limit: {path}")
    if files > 20000:
        raise ValueError("Site exceeds Pages' file-count limit")
    if not (site / "index.html").is_file():
        raise ValueError("Missing index.html")
    health = json.loads((site / "health.json").read_text())
    if health.get("service") != "dustymenu-packages" or health.get("status") != "online":
        raise ValueError("Invalid health endpoint")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    settings = commands.add_parser("settings")
    settings.add_argument("--spec", required=True)
    package = commands.add_parser("bundle")
    package.add_argument("--spec", required=True)
    package.add_argument("--input", required=True)
    package.add_argument("--output", required=True)
    site = commands.add_parser("check-site")
    site.add_argument("--site", required=True)
    args = parser.parse_args()
    try:
        if args.command == "settings":
            spec = read_spec(args.spec)
            for name, field in (("repository", "repository"), ("commit", "commit"), ("libtwl", "libtwlCommit"), ("image", "toolchainImage")):
                print(f"{name}={spec[field]}")
        elif args.command == "bundle":
            manifest = bundle(read_spec(args.spec), args.input, args.output)
            print(f"Prepared {len(manifest['files'])} files; qualification pending")
        else:
            check_site(args.site)
            print("Static site validation passed")
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
