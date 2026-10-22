#!/usr/bin/env python3
"""Build one pinned emulator package inside its digest-pinned container."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import emulators


def git_output(workspace, *arguments):
    return subprocess.check_output(["git", "-C", str(workspace), *arguments], text=True).strip()


def prepare_inputs(spec, upstream):
    if spec["id"] != "snemulds-06a":
        return
    # The historical image has no unzip; prepare these inputs on the host.
    expected = {"ds_arm7_snemulds.ld", "ds_arm7_snemulds.specs",
                "ds_arm9_snemulds.ld", "ds_arm9_snemulds.specs"}
    destination = upstream / ".dusty-build" / "linker-files"
    with zipfile.ZipFile(upstream / "linker_files.zip") as archive:
        entries = archive.infolist()
        if len(entries) != len(expected) or {entry.filename for entry in entries} != expected:
            raise ValueError("Unexpected SNEmulDS linker archive inventory")
        for entry in entries:
            if not 0 < entry.file_size <= 65536 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Invalid SNEmulDS linker archive entry")
        destination.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            (destination / entry.filename).write_bytes(archive.read(entry))


def run(spec, workspace, container=False):
    workspace = Path(workspace).resolve()
    upstream = workspace / "upstream"
    if not upstream.is_dir():
        raise ValueError("Missing upstream checkout")
    if git_output(upstream, "rev-parse", "HEAD") != spec["commit"]:
        raise ValueError("Upstream checkout does not match the pinned commit")
    submodule = spec.get("pinnedSubmodule")
    if submodule:
        path = upstream / submodule["path"]
        if not path.is_dir() or git_output(path, "rev-parse", "HEAD") != submodule["commit"]:
            raise ValueError("Pinned submodule does not match the spec")
    prepare_inputs(spec, upstream)
    package_root = Path(__file__).resolve().parents[1]
    if container:
        # Actions and Python stay on the modern host; old compiler images only
        # execute shell build commands and need no package-manager updates.
        subprocess.run([
            "docker", "run", "--rm", "-i",
            "--mount", f"type=bind,source={workspace},target=/workspace",
            "--mount", f"type=bind,source={package_root},target=/builder,readonly",
            "--workdir", "/workspace",
            "--env", "DUSTY_PACKAGE_ROOT=/builder", "--env", "LC_ALL=C", "--env", "TZ=UTC",
            "--entrypoint", "/bin/bash", spec["toolchainImage"], "-euxo", "pipefail", "-s",
        ], input="\n".join(spec["build"]["commands"]) + "\n", text=True, check=True)
    else:
        environment = os.environ.copy()
        environment.setdefault("LC_ALL", "C")
        environment.setdefault("TZ", "UTC")
        environment["DUSTY_PACKAGE_ROOT"] = str(package_root)
        for command in spec["build"]["commands"]:
            print(f"+ {command}", flush=True)
            subprocess.run(["/bin/bash", "-euo", "pipefail", "-c", command],
                           cwd=workspace, env=environment, check=True)
    if spec["id"] == "gbarunner3":
        # The host owns the checkout; do not invoke Git as container root.
        subprocess.run(["git", "-C", str(upstream), "diff", "--exit-code", "--", "configs"],
                       check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--container", action="store_true",
                        help="Compile in the spec's pinned Docker image; package on the host")
    args = parser.parse_args()
    try:
        spec = emulators.read_spec(args.spec)
        run(spec, args.workspace, container=args.container)
        manifest = emulators.bundle(spec, args.workspace, args.output)
        print(f"Built {manifest['id']} from {manifest['upstream']['commit']} "
              f"({len(manifest['files'])} files, {manifest['provenance']})")
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
