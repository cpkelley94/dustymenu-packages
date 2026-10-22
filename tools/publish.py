#!/usr/bin/env python3
"""Publish a complete signed GBARunner3 package as bounded static Pages assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from packages import read_spec, checked_file, check_nds, json_bytes, check_site, MAX_TOTAL, MAX_MANIFEST


def public_key(key):
    der = subprocess.check_output(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"])
    if len(der) != 44 or der[:12].hex() != "302a300506032b6570032100":
        raise ValueError("Publisher key must be Ed25519")
    return der[12:].hex()


def publish(spec, bundle, site, key, source_archive, sequence, expected_key):
    bundle, site, key, source_archive = map(Path, (bundle, site, key, source_archive))
    if type(sequence) is not int or not 0 < sequence <= 0xffffffff:
        raise ValueError("Sequence must be a positive uint32")
    if public_key(key) != expected_key:
        raise ValueError("Signing key differs from pinned device publisher")
    if key.resolve().is_relative_to(site.resolve()):
        raise ValueError("Signing key must stay outside the public site")
    inventory = json.loads(checked_file(bundle / "manifest.json", bundle))
    expected_upstream = {field: spec[field] for field in ("repository", "commit", "libtwlCommit", "toolchainImage")}
    if inventory.get("format") != "dustymenu-build-bundle-v1" or inventory.get("id") != "gbarunner3" or inventory.get("upstream") != expected_upstream:
        raise ValueError("Bundle provenance does not match the pinned build")
    entries = inventory["files"]
    if len(entries) != spec["expectedConfigs"] + 1 or len({entry["path"] for entry in entries}) != len(entries):
        raise ValueError("Incorrect or duplicate bundle inventory")
    version = spec["commit"][:12] + "-dev"
    release = f"releases/gbarunner3/{spec['commit']}"
    files, payload = [], bytearray()
    archive = bundle / f"GBARunner3-{spec['commit']}.zip"
    with zipfile.ZipFile(archive) as zipped:
        if sorted(zipped.namelist()) != sorted(entry["path"] for entry in entries):
            raise ValueError("Archive does not exactly match the inventory")
        for entry in entries:
            name, size = entry["path"], entry["size"]
            if type(size) is not int or not 0 < size <= 16 * 1024 * 1024 or len(payload) + size > MAX_TOTAL:
                raise ValueError("Invalid package file size")
            if zipped.getinfo(name).file_size != size:
                raise ValueError("Incorrect archive size")
            data = zipped.read(name)
            if hashlib.sha512(data).hexdigest() != entry["sha512"]:
                raise ValueError("Bundle hash mismatch")
            if name == "GBARunner3.nds" and entry["role"] == "executable":
                check_nds(data)
                role = "executable"
            elif re.fullmatch(r"_gba/configs/[A-Z0-9]{6}\.json", name) and entry["role"] == "compatibility-config":
                if len(data) > 65536 or not isinstance(json.loads(data), dict):
                    raise ValueError("Invalid compatibility config")
                role = "default-config"
            else:
                raise ValueError("Unexpected package destination/role")
            files.append({"destination": "/" + name, "role": role, "size": size, "sha512": entry["sha512"]})
            payload.extend(data)
    if sum(file["role"] == "executable" for file in files) != 1:
        raise ValueError("Missing or duplicate executable")
    sources = source_archive.read_bytes()
    if not sources or len(sources) > 25 * 1024 * 1024:
        raise ValueError("Corresponding-source archive exceeds Pages limits")
    source_name = f"{release}/source-{hashlib.sha256(sources).hexdigest()}.tar.gz"
    notices = (f"GBARunner3 development build {spec['commit']}\n"
               f"Upstream: https://github.com/{spec['repository']}/tree/{spec['commit']}\n"
               f"libtwl: {spec['libtwlCommit']}\nToolchain: {spec['toolchainImage']}\n"
               f"Corresponding source and original notices: /v2/{source_name}\n"
               "No game ROMs or proprietary BIOS files are included. Hardware qualification is pending.\n").encode()
    files.append({"destination": "/_pico/packages/gbarunner3-notices.txt", "role": "license", "size": len(notices), "sha512": hashlib.sha512(notices).hexdigest()})
    payload.extend(notices)
    if len(payload) > min(MAX_TOTAL, 25 * 1024 * 1024):
        raise ValueError("Package payload exceeds bounds")
    payload_hash = hashlib.sha512(payload).hexdigest()
    payload_name = f"{release}/payload-{payload_hash}.pkg"
    manifest = {"schema": 2, "id": "gbarunner3", "version": version,
                "payload": {"source": payload_name, "size": len(payload), "sha512": payload_hash}, "files": files}
    raw_manifest = json_bytes(manifest)
    if len(raw_manifest) > MAX_MANIFEST:
        raise ValueError("Package manifest exceeds 256 KiB")
    manifest_hash = hashlib.sha512(raw_manifest).hexdigest()
    manifest_name = f"{release}/manifest-{manifest_hash}.json"
    catalog = {"schema": 2, "sequence": sequence, "packages": [{
        "id": "gbarunner3", "name": "GBARunner3", "kind": "bundle", "system": "gba", "version": version,
        "destination": "/GBARunner3.nds", "source": manifest_name, "size": len(raw_manifest),
        "sha512": manifest_hash, "totalSize": len(payload), "extensions": ["gba", "agb"]}]}
    raw_catalog = json_bytes(catalog)
    if len(raw_catalog) > 32768:
        raise ValueError("Catalog exceeds 32 KiB")
    previous = site / "v2/catalog.bin"
    if previous.exists():
        old = previous.read_bytes()
        if not 64 < len(old) <= 32832:
            raise ValueError("Previous signed catalog exceeds bounds")
        # Existing snapshots are our own release artifacts; verify them before
        # trusting the sequence and publishing over an older deployment.
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / "catalog").write_bytes(old[64:]); (work / "sig").write_bytes(old[:64])
            subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(work / "public.pem")], check=True, capture_output=True)
            subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(work / "public.pem"),
                            "-in", str(work / "catalog"), "-sigfile", str(work / "sig")], check=True, capture_output=True)
        if sequence <= json.loads(old[64:])["sequence"]:
            raise ValueError("Publication sequence must increase")
    for relative, data in ((payload_name, payload), (manifest_name, raw_manifest), (source_name, sources)):
        target = site / "v2" / relative
        if target.exists() and target.read_bytes() != data:
            raise ValueError("Refusing to change an immutable release asset")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with tempfile.TemporaryDirectory() as temporary:
        raw, sig = Path(temporary) / "catalog", Path(temporary) / "signature"
        raw.write_bytes(raw_catalog)
        subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(raw), "-out", str(sig)], check=True, capture_output=True)
        previous.write_bytes(sig.read_bytes() + raw_catalog)
    (site / "v2/publisher-key.txt").write_text(expected_key + "\n")
    check_site(site)
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("spec", "bundle", "site", "key", "source-archive"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--sequence", type=int, required=True)
    args = parser.parse_args()
    publisher = json.loads((Path(__file__).resolve().parents[1] / "packages/publisher.json").read_text())
    result = publish(read_spec(args.spec), args.bundle, args.site, args.key, args.source_archive, args.sequence, publisher["publicKey"])
    print(f"Published signed GBARunner3 catalog sequence {result['sequence']}")


if __name__ == "__main__":
    main()
