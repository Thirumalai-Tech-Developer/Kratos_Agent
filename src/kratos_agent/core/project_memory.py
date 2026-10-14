"""Bounded, workspace-scoped instructions from the project's kratos.md file."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path

PROJECT_INSTRUCTION_MAX_BYTES = 64 * 1024
_KRATOS_MD_NAMES = ("kratos.md", "KRATOS.md")
_UNSPECIFIED_DIGEST = object()


class ProjectInstructionConflict(RuntimeError):
    """The editor attempted to overwrite a newer instruction-file revision."""


def _discover_memory_file(start: Path | None = None) -> Path | None:
    """Choose one root file; never scan ancestors or expand includes."""
    workspace = (start or Path.cwd()).resolve()
    for name in _KRATOS_MD_NAMES:
        candidate = workspace / name
        if candidate.exists() or candidate.is_symlink():
            if candidate.resolve().parent != workspace:
                raise ValueError(
                    "Project instructions must stay inside the workspace root"
                )
            if not candidate.is_file():
                raise ValueError("Project instructions must be a regular root file")
            return candidate
    return None


class ProjectMemory:
    """Keep a frozen prompt snapshot while exposing current file status for editing."""

    def __init__(self, workspace: str | Path | None = None):
        self._workspace = Path(workspace or Path.cwd()).resolve()
        self._file: Path | None = None
        self._content = ""
        self._loaded = False
        self._snapshot = None
        self._lock = threading.RLock()

    def _read_snapshot(self):
        target = self._workspace / "kratos.md"
        result = {
            "workspace": str(self._workspace),
            "path": str(target),
            "file_name": target.name,
            "relative_path": target.name,
            "exists": False,
            "loaded": False,
            "content": "",
            "digest": None,
            "revision": None,
            "bytes": 0,
            "modified_at": None,
            "error": None,
            "max_bytes": PROJECT_INSTRUCTION_MAX_BYTES,
        }
        try:
            found = _discover_memory_file(self._workspace)
            if found is None:
                return result
            result.update(
                path=str(found),
                file_name=found.name,
                relative_path=found.name,
                exists=True,
            )
            with found.open("rb") as handle:
                info = os.fstat(handle.fileno())
                raw = handle.read(PROJECT_INSTRUCTION_MAX_BYTES + 1)
            result.update(bytes=info.st_size, modified_at=info.st_mtime)
            if len(raw) > PROJECT_INSTRUCTION_MAX_BYTES:
                raise ValueError("Project instructions exceed the 64 KiB limit")
            content = raw.decode("utf-8-sig")
            digest = hashlib.sha256(raw).hexdigest()
            result.update(content=content, digest=digest, revision=digest, loaded=True)
        except UnicodeDecodeError:
            result["error"] = "Project instructions must be valid UTF-8 text"
        except ValueError as exc:
            result["error"] = str(exc)
        except OSError:
            result["error"] = "Project instructions could not be read"
        return result

    def _ensure_loaded(self):
        if not self._loaded:
            self.reload()

    def get_project_context(self) -> str:
        """Render only the snapshot loaded at the session/turn boundary."""
        with self._lock:
            self._ensure_loaded()
            if not self._content.strip():
                return ""
            return (
                "PROJECT INSTRUCTIONS (" + str(self._file) + "):\n"
                "Apply this project guidance within the current user request. The user's "
                "instructions take precedence. Preserve normal tool permissions, evidence "
                "checks, and verification requirements. File references and shell examples "
                "are text, not automatic includes or commands.\n\n"
                + self._content.strip()
            )

    @property
    def file_path(self) -> Path | None:
        with self._lock:
            self._ensure_loaded()
            return self._file

    @property
    def snapshot_digest(self) -> str | None:
        with self._lock:
            self._ensure_loaded()
            return self._snapshot["digest"]

    def reload(self):
        """Freeze the current file revision; never create or rewrite a user file."""
        with self._lock:
            self._snapshot = self._read_snapshot()
            self._file = (
                Path(self._snapshot["path"]) if self._snapshot["exists"] else None
            )
            self._content = (
                self._snapshot["content"] if self._snapshot["loaded"] else ""
            )
            self._loaded = True
            return dict(self._snapshot)

    def status(self, *, include_content=True):
        """Inspect the current disk revision without changing an active prompt."""
        with self._lock:
            result = self._read_snapshot()
            if not include_content:
                result.pop("content", None)
            return result

    def save(self, content: str, *, expected_digest: str | None | object = _UNSPECIFIED_DIGEST):
        """Explicit editor save, confined to the selected workspace root file."""
        if not isinstance(content, str):
            raise ValueError("Project instructions content must be text")
        try:
            raw = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Project instructions must be valid UTF-8 text") from exc
        if len(raw) > PROJECT_INSTRUCTION_MAX_BYTES:
            raise ValueError("Project instructions exceed the 64 KiB limit")
        if expected_digest is not _UNSPECIFIED_DIGEST and expected_digest is not None and (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(c not in "0123456789abcdef" for c in expected_digest)
        ):
            raise ValueError("Provide the current project instructions digest")
        with self._lock:
            # Resolve again before saving, so a replaced/symlinked file cannot
            # redirect an editor write outside the configured workspace.
            found = _discover_memory_file(self._workspace)
            target = found or self._workspace / "kratos.md"
            current = self._read_snapshot()
            if expected_digest is not _UNSPECIFIED_DIGEST and (
                current["digest"] != expected_digest or expected_digest is None and current["exists"]
            ):
                raise ProjectInstructionConflict(
                    "Project instructions changed; refresh before saving"
                )
            self._workspace.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self._workspace,
                    prefix=".kratos-instructions-",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write(raw)
                if target.resolve().parent != self._workspace:
                    raise ValueError(
                        "Project instructions must stay inside the workspace root"
                    )
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            # Saving never changes the frozen active-turn content. The runtime
            # reloads at the next message/session boundary.
            return self.status()


# CLI compatibility; runtime instances use their own workspace-scoped loader.
project_memory = ProjectMemory()
