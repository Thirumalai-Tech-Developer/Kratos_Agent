"""Import a reviewed OmniRoute working tree, without Git metadata or runtime data."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def git(source: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(source), *args])


def import_source(source: Path, root: Path) -> dict:
    destination = root / "services" / "omniroute"
    if destination.exists():
        raise RuntimeError(f"Import destination already exists: {destination}")
    paths = sorted(set(git(source, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")) - {""})
    files, excluded = [], []
    for name in paths:
        relative = Path(name)
        src = source / relative
        if relative.parts[0].startswith("_") or any(part in {".git", "node_modules"} for part in relative.parts) or (relative.name.startswith(".env") and not relative.name.endswith((".example", ".sample", ".template"))):
            excluded.append(name)
            continue
        if not src.exists():
            continue  # Preserve tracked deletions in the working snapshot.
        if src.is_symlink() or not src.is_file():
            raise RuntimeError(f"Review non-regular source before importing: {name}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        files.append({"path": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = {
        "source_commit": git(source, "rev-parse", "HEAD").decode().strip(),
        "source_branch": git(source, "branch", "--show-current").decode().strip(),
        "source_status": git(source, "status", "--short").decode().splitlines(),
        "files": files,
        "excluded": excluded,
    }
    output = root / "integration" / "omniroute-source.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    result = import_source(args.source.resolve(), Path(__file__).resolve().parents[2])
    print(f"Imported {len(result['files'])} files; excluded {len(result['excluded'])} private paths.")
