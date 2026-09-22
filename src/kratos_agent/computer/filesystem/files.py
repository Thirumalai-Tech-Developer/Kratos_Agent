"""Semantic object-oriented filesystem operations."""
from __future__ import annotations
import os
import shutil
import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

from kratos_agent.computer.state import ActionResult


class FileSystemEngine:
    """Provides high-level filesystem operations without requiring GUI File Explorer."""

    def list_files(self, path: str = ".", recursive: bool = False, max_items: int = 100) -> List[Dict[str, Any]]:
        """Lists files and directories with metadata (size, is_dir, modified)."""
        p = Path(path).resolve()
        if not p.exists():
            return []

        results: List[Dict[str, Any]] = []
        iterator = p.rglob("*") if recursive else p.iterdir()

        for item in iterator:
            try:
                stat = item.stat()
                results.append({
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size_bytes": stat.st_size if not item.is_dir() else 0,
                    "modified": stat.st_mtime,
                })
                if len(results) >= max_items:
                    break
            except (PermissionError, FileNotFoundError):
                pass

        return results

    def search_files(self, query: str, root: str = ".", limit: int = 50) -> List[str]:
        """Searches for files matching a glob pattern or substring."""
        p = Path(root).resolve()
        matches: List[str] = []
        pattern = f"*{query}*" if "*" not in query else query

        for item in p.rglob(pattern):
            matches.append(str(item))
            if len(matches) >= limit:
                break
        return matches

    def read_file(self, path: str, encoding: str = "utf-8", max_bytes: int = 1024 * 1024) -> str:
        """Reads content from a file up to max_bytes."""
        p = Path(path).resolve()
        if not p.exists():
            return f"Error: File '{path}' does not exist"
        try:
            with open(p, "r", encoding=encoding, errors="replace") as f:
                return f.read(max_bytes)
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, path: str, content: str, encoding: str = "utf-8", overwrite: bool = True) -> ActionResult:
        """Writes text content to a file."""
        p = Path(path).resolve()
        if p.exists() and not overwrite:
            return ActionResult(ok=False, action="file_write", detail="File exists and overwrite is False")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
            return ActionResult(ok=True, action="file_write", data={"path": str(p), "bytes": len(content.encode(encoding))})
        except Exception as e:
            return ActionResult(ok=False, action="file_write", detail=str(e))

    def move_file(self, src: str, dst: str) -> ActionResult:
        """Moves or renames a file or directory."""
        try:
            shutil.move(src, dst)
            return ActionResult(ok=True, action="file_move", data={"src": src, "dst": dst})
        except Exception as e:
            return ActionResult(ok=False, action="file_move", detail=str(e))

    def copy_file(self, src: str, dst: str) -> ActionResult:
        """Copies a file or directory."""
        try:
            s, d = Path(src), Path(dst)
            if s.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            return ActionResult(ok=True, action="file_copy", data={"src": src, "dst": dst})
        except Exception as e:
            return ActionResult(ok=False, action="file_copy", detail=str(e))

    def delete_file(self, path: str, permanent: bool = False) -> ActionResult:
        """Deletes a file or directory."""
        p = Path(path).resolve()
        if not p.exists():
            return ActionResult(ok=False, action="file_delete", detail="Target does not exist")
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            return ActionResult(ok=True, action="file_delete", data={"deleted": str(p)})
        except Exception as e:
            return ActionResult(ok=False, action="file_delete", detail=str(e))


_filesystem_engine: Optional[FileSystemEngine] = None


def get_filesystem_engine() -> FileSystemEngine:
    global _filesystem_engine
    if _filesystem_engine is None:
        _filesystem_engine = FileSystemEngine()
    return _filesystem_engine
