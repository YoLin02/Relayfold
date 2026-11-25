"""Build the application and publishing worker payload for an online update."""

import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def files(root, folder):
    for file in sorted((root / folder).rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            yield file


def pack(root, output):
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name in ("package.json", "THIRD_PARTY.md"):
            archive.write(root / name, f"app/{name}")
        for folder in ("electron", "dist", "licenses"):
            for file in files(root, folder):
                archive.write(file, "app/" + file.relative_to(root).as_posix())
        for file in files(root, "worker"):
            if file.suffix in {".py", ".txt"}:
                archive.write(file, file.relative_to(root).as_posix())


if __name__ == "__main__":
    pack(Path(sys.argv[1]), Path(sys.argv[2]))
