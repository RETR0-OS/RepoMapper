"""Create checksums and dependency/license inventories for a release directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    files = sorted(item for item in directory.rglob("*") if item.is_file())
    checksums = {
        item.relative_to(directory).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in files
    }
    (directory / "SHA256SUMS.json").write_text(
        json.dumps(checksums, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    licenses = subprocess.run(
        ["pip-licenses", "--format=json", "--with-license-file", "--no-license-path"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (directory / "python-dependency-licenses.json").write_text(licenses, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
