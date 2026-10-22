#!/usr/bin/env python3
"""Restore only bounded regular v2 assets from a previous public release snapshot."""
import argparse
from pathlib import Path, PurePosixPath
import tarfile


def restore(archive, site):
    site=Path(site)
    with tarfile.open(archive) as package:
        members=[]; total=0; names=set()
        for member in package.getmembers():
            name=member.name.removeprefix("./")
            if name in ("", "."): continue
            path=PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe snapshot entry")
            # Root static files come from this checkout, never an older release.
            if path.parts[0]!="v2": continue
            if name in names or member.size>25*1024*1024: raise ValueError("Invalid snapshot asset")
            names.add(name);total+=member.size
            if len(names)>20000 or total>512*1024*1024: raise ValueError("Snapshot exceeds bounds")
            members.append((member,path))
        for member,path in members:
            target=site / str(path)
            if any(item.is_symlink() for item in (target,*target.parents)): raise ValueError("Symlink in output")
            if member.isdir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with package.extractfile(member) as source,target.open("wb") as output:
                    while data:=source.read(65536): output.write(data)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--archive",required=True);parser.add_argument("--site",required=True)
    args=parser.parse_args();restore(args.archive,args.site)
