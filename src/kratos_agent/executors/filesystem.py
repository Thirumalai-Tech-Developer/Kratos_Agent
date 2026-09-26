from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any


class FileExecutor:
    def write(self, path: str, content: str) -> dict[str, Any]:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {"ok": target.exists(), "verified": target.exists(), "path": str(target), "content_hash": digest}

    def copy(self, src: str, dst: str) -> dict[str, Any]:
        target = Path(dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return {"ok": target.exists(), "verified": target.exists(), "path": str(target)}

    def move(self, src: str, dst: str) -> dict[str, Any]:
        target = Path(shutil.move(src, dst))
        return {"ok": target.exists(), "verified": target.exists(), "path": str(target)}

    def delete(self, path: str) -> dict[str, Any]:
        target = Path(path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        return {"ok": not target.exists(), "verified": not target.exists(), "path": str(target)}
