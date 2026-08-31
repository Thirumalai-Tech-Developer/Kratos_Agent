"""Workspace tracker: monitors files created, modified, deleted, and inspected during agent execution.

Provides clean structured summaries of workspace changes without dumping excessive text.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set


class WorkspaceTracker:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        self.created_files: Set[str] = set()
        self.modified_files: Set[str] = set()
        self.deleted_files: Set[str] = set()
        self.inspected_files: Set[str] = set()
        self.executed_commands: List[Dict[str, Any]] = []

    def reset(self) -> None:
        self.created_files.clear()
        self.modified_files.clear()
        self.deleted_files.clear()
        self.inspected_files.clear()
        self.executed_commands.clear()

    def _normalize(self, file_path: str) -> str:
        p = file_path.replace("\\", "/").strip().lstrip("./")
        return p

    def record_file_created(self, file_path: str) -> None:
        norm = self._normalize(file_path)
        if norm:
            self.created_files.add(norm)
            self.modified_files.discard(norm)

    def record_file_modified(self, file_path: str) -> None:
        norm = self._normalize(file_path)
        if norm and norm not in self.created_files:
            self.modified_files.add(norm)

    def record_file_deleted(self, file_path: str) -> None:
        norm = self._normalize(file_path)
        if norm:
            self.deleted_files.add(norm)
            self.created_files.discard(norm)
            self.modified_files.discard(norm)

    def record_file_inspected(self, file_path: str) -> None:
        norm = self._normalize(file_path)
        if norm:
            self.inspected_files.add(norm)

    def record_command(self, command: str, returncode: int = 0, summary: str = "") -> None:
        self.executed_commands.append({
            "command": command,
            "returncode": returncode,
            "summary": summary,
        })

    @property
    def total_changed_count(self) -> int:
        return len(self.created_files) + len(self.modified_files) + len(self.deleted_files)

    @property
    def all_changed_files(self) -> List[str]:
        combined = sorted(list(self.created_files | self.modified_files))
        return combined

    def summary(self) -> Dict[str, Any]:
        return {
            "created": sorted(list(self.created_files)),
            "modified": sorted(list(self.modified_files)),
            "deleted": sorted(list(self.deleted_files)),
            "inspected_count": len(self.inspected_files),
            "total_changed": self.total_changed_count,
            "commands_count": len(self.executed_commands),
        }
