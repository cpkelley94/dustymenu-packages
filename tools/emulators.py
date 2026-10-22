#!/usr/bin/env python3
"""Validate schema-3 emulator specs and build deterministic package bundles."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import tarfile
import zipfile

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_FILES = 512
MAX_MANIFEST = 256 * 1024
MAX_SOURCE = 25 * 1024 * 1024

DESCRIPTORS = {
    "gbarunner3": {
        "name": "GBARunner3", "system": "gba", "entry": "/GBARunner3.nds",
        "extensions": ["gba", "agb"], "manual": False,
    },
    "gbarunner2": {
        "name": "GBARunner2", "system": "gba", "entry": "/emulators/gbarunner2.nds",
        "extensions": ["gba", "agb"], "manual": False,
    },
    "gameyob": {
        "name": "GameYob", "system": "gb", "entry": "/emulators/gameyob.nds",
        "extensions": ["gb", "gbc", "sgb"], "manual": False,
    },
    "nesds": {
        "name": "nesDS", "system": "nes", "entry": "/emulators/nesds.nds",
        "extensions": ["nes", "fds"], "manual": False,
    },
    "snemulds-06a": {
        "name": "SNEmulDS 0.6a", "system": "snes", "entry": "/emulators/snemulds-06a.nds",
        "extensions": ["smc", "sfc"], "manual": False,
    },
    "snemulds-06d": {
        "name": "SNEmulDS 0.6d (manual)", "system": "snes",
        "entry": "/emulators/snemulds-06d/ToolchainGenericDS-multiboot.nds",
        "extensions": ["smc", "sfc"], "manual": True,
    },
    "picodrivetwl": {
        "name": "PicoDriveTWL", "system": "genesis", "entry": "/emulators/picodrivetwl.nds",
        "extensions": ["md", "gen", "bin", "smd"], "manual": False,
    },
}
PACKAGE_ORDER = tuple(DESCRIPTORS)
SUPPORT_FILES = {
    "snemulds-06d": {
        "/emulators/snemulds-06d/SNEmulDS.nds",
        "/emulators/snemulds-06d/tgds_multiboot_payload_ntr.binlzss",
        "/emulators/snemulds-06d/toolchaingenericds-multiboot-config.txt",
    },
}
DEFAULT_CONFIGS = {
    "gbarunner3": re.compile(r"^/_gba/configs/[A-Z0-9]{6}\.json$"),
    "snemulds-06a": re.compile(r"^/snemul\.cfg$"),
}
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
IMAGE = re.compile(r"^[a-z0-9._/-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def safe_path(path):
    if not path or not path.startswith("/") or path.endswith("/") or len(path) > 220:
        return False
    if any(ord(char) < 32 or char in "\\:" or ord(char) == 127 for char in path):
        return False
    parts = path.split("/")[1:]
    return all(part and part not in (".", "..") for part in parts)


def checked_file(path, root):
    path = Path(path)
    root = Path(root).resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or path.is_symlink():
        raise ValueError(f"Input escapes the workspace or is a symlink: {path}")
    for item in path.parents:
        if item.is_symlink():
            raise ValueError(f"Symlink in input path: {item}")
        if item.resolve() == root:
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


def read_spec(path):
    path = Path(path)
    try:
        spec = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read package spec {path}: {error}") from error
    if not isinstance(spec, dict) or spec.get("schema") != 1:
        raise ValueError("Package spec must be a schema-1 object")
    package_id = spec.get("id")
    descriptor = DESCRIPTORS.get(package_id)
    if descriptor is None:
        raise ValueError("Unknown package id")
    if spec.get("name") != descriptor["name"] or spec.get("system") != descriptor["system"]:
        raise ValueError("Spec name/system does not match the client descriptor")
    if spec.get("extensions") != descriptor["extensions"]:
        raise ValueError("Spec extensions must exactly match the client descriptor order")
    if spec.get("manual") is not descriptor["manual"]:
        raise ValueError("Spec launch mode does not match the client descriptor")
    if not REPOSITORY.fullmatch(spec.get("repository", "")):
        raise ValueError("Repository must be a pinned GitHub owner/name")
    if not COMMIT.fullmatch(spec.get("commit", "")):
        raise ValueError("commit must be a full pinned commit")
    if not IMAGE.fullmatch(spec.get("toolchainImage", "")):
        raise ValueError("Toolchain must be pinned by digest")
    if spec.get("qualification") != "pending":
        raise ValueError("This tool only produces pending qualification artifacts")
    if spec.get("provenance") not in ("source", "upstream-release"):
        raise ValueError("Unknown build provenance")
    if not isinstance(spec.get("license"), str) or not spec["license"].strip():
        raise ValueError("Missing license description")
    if not isinstance(spec.get("notes"), str) or len(spec["notes"]) > 1000:
        raise ValueError("Missing or oversized notes")
    submodule = spec.get("pinnedSubmodule")
    if submodule is not None:
        if not isinstance(submodule, dict) or not safe_path("/" + str(submodule.get("path", ""))) \
                or not COMMIT.fullmatch(submodule.get("commit", "")):
            raise ValueError("Invalid pinned submodule")
    build = spec.get("build")
    if not isinstance(build, dict):
        raise ValueError("Missing build recipe")
    commands = build.get("commands")
    if not isinstance(commands, list) or len(commands) > 16 or not all(
            isinstance(command, str) and 0 < len(command) <= 1000 and "\n" not in command
            for command in commands):
        raise ValueError("Invalid build commands")
    if spec["provenance"] == "upstream-release" and commands:
        raise ValueError("Upstream-release packages must not run build commands")
    outputs = build.get("outputs")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= MAX_FILES:
        raise ValueError("Invalid build outputs")
    seen = set()
    for output in outputs:
        if not isinstance(output, dict) or output.get("role") not in (
                "executable", "default-config", "support-data"):
            raise ValueError("Invalid output role")
        has_path = isinstance(output.get("path"), str)
        has_glob = isinstance(output.get("glob"), str)
        if has_path == has_glob:
            raise ValueError("Output must define exactly one of path/glob")
        if has_path:
            _valid_source(output["path"])
            destinations = [output.get("destination")]
        else:
            _valid_glob(output["glob"])
            if not isinstance(output.get("namePattern"), str):
                raise ValueError("Glob outputs need a name pattern")
            try:
                re.compile(output["namePattern"])
            except re.error as error:
                raise ValueError("Invalid output name pattern") from error
            if not isinstance(output.get("expected"), int) or not 1 <= output["expected"] <= MAX_FILES:
                raise ValueError("Glob outputs need a bounded expected count")
            destination = output.get("destination")
            if not isinstance(destination, str) or destination.count("{name}") != 1:
                raise ValueError("Glob destination must contain exactly one {name}")
            destinations = [destination]
        for destination in destinations:
            _valid_destination(package_id, output["role"], destination)
            if destination in seen:
                raise ValueError(f"Duplicate destination: {destination}")
            seen.add(destination)
    return spec


def _valid_source(path):
    if not isinstance(path, str) or not path.startswith("upstream/") or path.endswith("/"):
        raise ValueError("Build output must be a file under upstream/")
    if not safe_path("/" + path):
        raise ValueError("Invalid build output path")
    if "*" in path or "?" in path or "[" in path:
        raise ValueError("Literal output path contains a wildcard")


def _valid_glob(pattern):
    if pattern.count("*") != 1 or not pattern.startswith("upstream/"):
        raise ValueError("Only one wildcard in a path under upstream/ is supported")
    _valid_source(pattern.replace("*", "X", 1))


def _valid_destination(package_id, role, destination):
    if not safe_path(destination):
        raise ValueError(f"Invalid package destination: {destination}")
    descriptor = DESCRIPTORS[package_id]
    if role == "executable":
        if destination != descriptor["entry"]:
            raise ValueError("Executable destination must match the client descriptor")
        return
    if role == "default-config":
        if "{name}" in destination:
            if package_id != "gbarunner3" or destination != "/_gba/configs/{name}":
                raise ValueError(f"Invalid default-config destination template: {destination}")
            return
        pattern = DEFAULT_CONFIGS.get(package_id)
        if not pattern or not pattern.fullmatch(destination):
            raise ValueError(f"Invalid default-config destination: {destination}")
        return
    if role == "support-data":
        if destination not in SUPPORT_FILES.get(package_id, set()):
            raise ValueError(f"Invalid support-data destination: {destination}")
        return
    raise ValueError(f"Unknown role: {role}")


def load_specs(directory):
    specs = [read_spec(path) for path in sorted(Path(directory).glob("*.json"))]
    ids = [spec["id"] for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate package ids")
    unknown = set(ids) - set(DESCRIPTORS)
    if unknown:
        raise ValueError(f"Unknown package specs: {sorted(unknown)}")
    return sorted(specs, key=lambda spec: PACKAGE_ORDER.index(spec["id"]))


def collect_outputs(spec, workspace):
    workspace = Path(workspace).resolve()
    files = []
    for output in spec["build"]["outputs"]:
        if "path" in output:
            source = workspace / output["path"]
            data = checked_file(source, workspace / "upstream")
            files.append((output["destination"], output["role"], data))
            continue
        matches = sorted(workspace.glob(output["glob"]))
        if len(matches) != output["expected"]:
            raise ValueError(
                f"{spec['id']}: expected {output['expected']} files for {output['glob']}, found {len(matches)}")
        for source in matches:
            if source.is_symlink() or not source.is_file():
                raise ValueError(f"Invalid glob input: {source}")
            if not re.fullmatch(output["namePattern"], source.name):
                raise ValueError(f"Unexpected glob filename: {source.name}")
            data = checked_file(source, workspace / "upstream")
            files.append((output["destination"].replace("{name}", source.name), output["role"], data))
    destinations = [destination for destination, _, _ in files]
    if len(destinations) != len(set(destinations)):
        raise ValueError(f"{spec['id']}: duplicate package destinations")
    if len(files) > MAX_FILES or sum(len(data) for _, _, data in files) > MAX_TOTAL:
        raise ValueError(f"{spec['id']}: package exceeds inventory/size limits")
    executable_count = 0
    for destination, role, data in files:
        _valid_destination(spec["id"], role, destination)
        if not data or len(data) > MAX_FILE:
            raise ValueError(f"{spec['id']}: invalid file size for {destination}")
        if role == "executable":
            executable_count += 1
            check_nds(data)
        elif role == "default-config" and spec["id"] == "gbarunner3":
            if len(data) > 65536 or not isinstance(json.loads(data), dict):
                raise ValueError(f"{spec['id']}: invalid compatibility config {destination}")
    if executable_count != 1:
        raise ValueError(f"{spec['id']}: package must contain exactly one executable")
    return files


def make_source_archive(workspace, output):
    workspace = Path(workspace).resolve()
    source = workspace / "upstream"
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Missing upstream source tree")
    if Path(output).resolve().is_relative_to(source.resolve()):
        raise ValueError("Source archive must stay outside the source tree")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
            for path in sorted(source.rglob("*")):
                if ".git" in path.parts:
                    continue
                relative = path.relative_to(workspace)
                if path.is_symlink():
                    raise ValueError(f"Symlink in source tree: {relative}")
                info = archive.gettarinfo(str(path), arcname=str(relative))
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                if path.is_file():
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
                elif path.is_dir():
                    info.mode = 0o755
                    archive.addfile(info)
    data = buffer.getvalue()
    if not 0 < len(data) <= MAX_SOURCE:
        raise ValueError("Corresponding-source archive exceeds the 25 MiB public limit")
    Path(output).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def bundle(spec, workspace, output):
    workspace = Path(workspace).resolve()
    output = Path(output)
    if output.resolve().is_relative_to(workspace / "upstream"):
        raise ValueError("Output must stay outside the upstream source tree")
    files = collect_outputs(spec, workspace)
    manifest = {
        "format": "dustymenu-build-bundle-v2",
        "id": spec["id"],
        "name": spec["name"],
        "system": spec["system"],
        "manual": spec["manual"],
        "qualification": "pending",
        "provenance": spec["provenance"],
        "license": spec["license"],
        "upstream": {
            "repository": spec["repository"],
            "commit": spec["commit"],
            "toolchainImage": spec["toolchainImage"],
        },
        "files": [
            {"path": destination, "size": len(data), "sha512": hashlib.sha512(data).hexdigest(), "role": role}
            for destination, role, data in files
        ],
    }
    if spec.get("pinnedSubmodule"):
        manifest["upstream"]["pinnedSubmodule"] = spec["pinnedSubmodule"]
    raw_manifest = json_bytes(manifest)
    if len(raw_manifest) > MAX_MANIFEST:
        raise ValueError("Manifest exceeds the 256 KiB limit")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{spec['name'].replace(' ', '-')}-{spec['commit']}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for destination, _, data in files:
            entry = zipfile.ZipInfo(destination.lstrip("/"), date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, data)
    (output / "manifest.json").write_bytes(raw_manifest)
    source = output / "source.tar.gz"
    make_source_archive(workspace, source)
    sums = []
    for path in (archive, output / "manifest.json", source):
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    (output / "SHA256SUMS").write_text("".join(sums))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    settings = commands.add_parser("settings")
    settings.add_argument("--spec", required=True)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--directory", default="packages/v3")
    package = commands.add_parser("bundle")
    package.add_argument("--spec", required=True)
    package.add_argument("--workspace", required=True)
    package.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "settings":
            spec = read_spec(args.spec)
            for name, field in (("repository", "repository"), ("commit", "commit"),
                                ("image", "toolchainImage"), ("provenance", "provenance")):
                print(f"{name}={spec[field]}")
        elif args.command == "matrix":
            specs = load_specs(args.directory)
            print(json.dumps([
                {"id": spec["id"], "repository": spec["repository"], "commit": spec["commit"],
                 "image": spec["toolchainImage"]}
                for spec in specs
            ], separators=(",", ":")))
        else:
            manifest = bundle(read_spec(args.spec), args.workspace, args.output)
            print(f"Prepared {len(manifest['files'])} files for {manifest['id']}; qualification pending")
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
