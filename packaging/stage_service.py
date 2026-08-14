"""Stage one signed service bundle and create its integrity manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

PROTOCOL = "hack-hydra.managed-service.v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    extension = args.extension.resolve()
    executable_name = "hydra-graph.exe" if args.target.startswith("win32-") else "hydra-graph"
    executable = source / executable_name
    if not executable.is_file():
        raise SystemExit(f"signed service executable is missing: {executable}")
    service_root = extension / "resources" / "service"
    destination = service_root / args.target
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    staged_executable = destination / executable_name
    digest = hashlib.sha256(staged_executable.read_bytes()).hexdigest()
    manifest = {
        "protocol": PROTOCOL,
        "targets": {
            args.target: {
                "path": f"resources/service/{args.target}/{executable_name}",
                "sha256": digest,
            }
        },
    }
    (service_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
