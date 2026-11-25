"""Extract a verified Relayfold update to an empty staging directory."""

import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path


def extract(source, destination):
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > 2048 or sum(item.file_size for item in members) > 64 * 1024**2:
            raise ValueError("Update payload exceeds its extraction limits.")

        names = set()
        for item in members:
            pieces = item.filename.split("/")
            if (item.is_dir() or len(pieces) < 2 or pieces[0] not in {"app", "worker"}
                    or any(not piece or piece in {".", ".."} or piece.endswith((".", " "))
                           or re.search(r'[<>:"\\|?*\x00-\x1f]', piece)
                           or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', piece, re.I)
                           for piece in pieces)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("Unexpected path in update payload.")
            name = item.filename.lower()
            if name in names:
                raise ValueError("Duplicate path in update payload.")
            names.add(name)

        required = {"app/package.json", "app/electron/main.cjs", "app/dist/index.html", "worker/main.py"}
        if not required <= names:
            raise ValueError("The update is missing a required application file.")

        for item in members:
            target = destination.joinpath(*item.filename.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)


if __name__ == "__main__":
    extract(Path(sys.argv[1]), Path(sys.argv[2]))
