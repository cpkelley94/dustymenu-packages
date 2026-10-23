#!/usr/bin/env python3
"""Publish all pinned emulator packages as one signed schema-3 catalog."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import emulators
from packages import check_site, MAX_MANIFEST, MAX_TOTAL


def public_key(key):
    der = subprocess.check_output(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"])
    if len(der) != 44 or der[:12].hex() != "302a300506032b6570032100":
        raise ValueError("Publisher key must be Ed25519")
    return der[12:].hex()


def load_bundles(directory):
    bundles = {}
    for manifest_path in sorted(Path(directory).rglob("manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid bundle manifest {manifest_path}: {error}") from error
        if manifest.get("format") != "dustymenu-build-bundle-v2":
            continue
        package_id = manifest.get("id")
        if package_id not in emulators.DESCRIPTORS or package_id in bundles:
            raise ValueError(f"Unknown or duplicate bundle id: {package_id}")
        bundles[package_id] = (manifest_path.parent, manifest)
    return bundles


def verify_previous(path, key, public):
    if not path.exists():
        return 0
    envelope = path.read_bytes()
    if not 64 < len(envelope) <= 32832:
        raise ValueError("Previous signed catalog exceeds bounds")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        (work / "catalog").write_bytes(envelope[64:])
        (work / "signature").write_bytes(envelope[:64])
        (work / "public.pem").write_bytes(
            subprocess.check_output(["openssl", "pkey", "-pubout", "-in", str(key)]))
        subprocess.run([
            "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(work / "public.pem"),
            "-in", str(work / "catalog"), "-sigfile", str(work / "signature"),
        ], check=True, capture_output=True)
    if public_key(key) != public:
        raise ValueError("Signing key differs from the pinned publisher")
    return json.loads(envelope[64:])["sequence"]


def add_immutable(site, relative, data):
    target = site / "v3" / relative
    if target.exists() and target.read_bytes() != data:
        raise ValueError(f"Refusing to change immutable release asset: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def package_assets(spec, bundle_dir, manifest, site):
    expected_upstream = {
        "repository": spec["repository"],
        "commit": spec["commit"],
        "toolchainImage": spec["toolchainImage"],
    }
    if spec.get("pinnedSubmodule"):
        expected_upstream["pinnedSubmodule"] = spec["pinnedSubmodule"]
    if manifest.get("id") != spec["id"] or manifest.get("system") != spec["system"] \
            or manifest.get("manual") is not spec["manual"] \
            or manifest.get("provenance") != spec["provenance"] \
            or type(manifest.get("revision", 1)) is not int \
            or manifest.get("revision", 1) != spec.get("revision", 1) \
            or manifest.get("license") != spec["license"] \
            or manifest.get("upstream") != expected_upstream:
        raise ValueError(f"{spec['id']}: bundle provenance does not match the pinned spec")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= emulators.MAX_FILES \
            or len({entry.get("path") for entry in entries}) != len(entries):
        raise ValueError(f"{spec['id']}: invalid bundle inventory")
    archive = bundle_dir / f"{spec['name'].replace(' ', '-')}-{spec['commit']}.zip"
    if not archive.is_file():
        raise ValueError(f"{spec['id']}: missing build archive")
    version = spec["commit"][:12] + "-dev"
    if spec.get("revision", 1) > 1:
        version += "-r" + str(spec["revision"])
    release = f"releases/{spec['id']}/{spec['commit']}"
    files, payload = [], bytearray()
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        if len(names) != len(set(names)) or sorted(names) != sorted(entry["path"].lstrip("/") for entry in entries):
            raise ValueError(f"{spec['id']}: archive does not exactly match the inventory")
        for entry in entries:
            name, size, role = entry.get("path"), entry.get("size"), entry.get("role")
            if not isinstance(name, str) or type(size) is not int or not 0 < size <= emulators.MAX_FILE \
                    or len(payload) + size > MAX_TOTAL:
                raise ValueError(f"{spec['id']}: invalid package file size")
            try:
                emulators._valid_destination(spec["id"], role, name)
            except ValueError as error:
                raise ValueError(f"{spec['id']}: {error}") from error
            data = zipped.read(name.lstrip("/"))
            if len(data) != size or hashlib.sha512(data).hexdigest() != entry.get("sha512"):
                raise ValueError(f"{spec['id']}: bundle hash mismatch for {name}")
            if role == "executable":
                emulators.check_nds(data)
            files.append({"destination": name, "role": role, "size": size,
                          "sha512": entry["sha512"]})
            payload.extend(data)
    if sum(file["role"] == "executable" for file in files) != 1:
        raise ValueError(f"{spec['id']}: missing or duplicate executable")
    sources = (bundle_dir / "source.tar.gz").read_bytes()
    if not sources or len(sources) > emulators.MAX_SOURCE:
        raise ValueError(f"{spec['id']}: corresponding-source archive exceeds limits")
    source_name = f"{release}/source-{hashlib.sha256(sources).hexdigest()}.tar.gz"
    add_immutable(site, source_name, sources)
    notice = (
        f"{spec['name']} development build {spec['commit']}\n"
        f"Package id: {spec['id']}\n"
        f"Upstream: https://github.com/{spec['repository']}/tree/{spec['commit']}\n"
        f"Provenance: {spec['provenance']}\n"
        f"Toolchain/package image: {spec['toolchainImage']}\n"
        f"License: {spec['license']}\n"
        f"Corresponding source and original notices: /v3/{source_name}\n"
        f"{spec['notes']}\n"
        "No game ROMs or proprietary BIOS files are included. Hardware qualification is pending.\n"
    ).encode()
    if len(notice) > 65536:
        raise ValueError(f"{spec['id']}: notice is too large")
    notice_path = f"/_pico/packages/{spec['id']}-notices.txt"
    files.append({"destination": notice_path, "role": "license", "size": len(notice),
                  "sha512": hashlib.sha512(notice).hexdigest()})
    payload.extend(notice)
    if len(payload) > min(MAX_TOTAL, 25 * 1024 * 1024):
        raise ValueError(f"{spec['id']}: package payload exceeds bounds")
    payload_hash = hashlib.sha512(payload).hexdigest()
    payload_name = f"{release}/payload-{payload_hash}.pkg"
    add_immutable(site, payload_name, bytes(payload))
    package_manifest = {
        "schema": 3,
        "id": spec["id"],
        "version": version,
        "payload": {"source": payload_name, "size": len(payload), "sha512": payload_hash},
        "files": files,
    }
    raw_manifest = emulators.json_bytes(package_manifest)
    if len(raw_manifest) > MAX_MANIFEST:
        raise ValueError(f"{spec['id']}: manifest exceeds 256 KiB")
    manifest_hash = hashlib.sha512(raw_manifest).hexdigest()
    manifest_name = f"{release}/manifest-{manifest_hash}.json"
    add_immutable(site, manifest_name, raw_manifest)
    return {
        "id": spec["id"],
        "name": spec["name"],
        "kind": "bundle",
        "system": spec["system"],
        "version": version,
        "destination": emulators.DESCRIPTORS[spec["id"]]["entry"],
        "source": manifest_name,
        "size": len(raw_manifest),
        "sha512": manifest_hash,
        "totalSize": len(payload),
        "extensions": spec["extensions"],
        "manual": spec["manual"],
    }


def publish(specs, bundles_root, site, key, sequence, expected_key):
    site, key = Path(site), Path(key)
    if type(sequence) is not int or not 0 < sequence <= 0xffffffff:
        raise ValueError("Sequence must be a positive uint32")
    if public_key(key) != expected_key:
        raise ValueError("Signing key differs from the pinned device publisher")
    if key.resolve().is_relative_to(site.resolve()):
        raise ValueError("Signing key must stay outside the public site")
    bundles = load_bundles(bundles_root)
    expected_ids = {spec["id"] for spec in specs}
    if set(bundles) != expected_ids:
        raise ValueError(f"Bundle ids differ from specs: missing {sorted(expected_ids - set(bundles))}, "
                         f"unexpected {sorted(set(bundles) - expected_ids)}")
    previous = verify_previous(site / "v3/catalog.bin", key, expected_key)
    if previous and sequence <= previous:
        raise ValueError("Publication sequence must increase")
    packages = [package_assets(spec, *bundles[spec["id"]], site) for spec in specs]
    catalog = {"schema": 3, "sequence": sequence, "packages": packages}
    raw_catalog = emulators.json_bytes(catalog)
    if len(raw_catalog) > 32768:
        raise ValueError("Catalog exceeds 32 KiB")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        (work / "catalog").write_bytes(raw_catalog)
        subprocess.run([
            "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key),
            "-in", str(work / "catalog"), "-out", str(work / "signature"),
        ], check=True, capture_output=True)
        (site / "v3/catalog.bin").parent.mkdir(parents=True, exist_ok=True)
        (site / "v3/catalog.bin").write_bytes((work / "signature").read_bytes() + raw_catalog)
    (site / "v3/publisher-key.txt").write_text(expected_key + "\n")
    check_site(site)
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-directory", default="packages/v3")
    parser.add_argument("--bundles", required=True)
    parser.add_argument("--site", default="public")
    parser.add_argument("--key", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    args = parser.parse_args()
    try:
        publisher = json.loads(
            (Path(__file__).resolve().parents[1] / "packages/publisher.json").read_text())
        result = publish(emulators.load_specs(args.spec_directory), args.bundles,
                         args.site, args.key, args.sequence, publisher["publicKey"])
        print(f"Published signed schema-3 catalog sequence {result['sequence']} "
              f"with {len(result['packages'])} packages")
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
