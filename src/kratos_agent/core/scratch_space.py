"""Private, per-turn storage for disposable research helpers and extracts."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path


class ScratchSpace:
    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="kratos-research-")
        self.root = Path(self._temporary.name).resolve()
        (self.root / "scratch").mkdir()

    def owns(self, value: str) -> bool:
        try:
            return Path(value).resolve().is_relative_to(self.root)
        except (OSError, ValueError):
            return False

    def resolve(self, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized == "scratch" or normalized.startswith("scratch/"):
            target = (self.root / normalized).resolve()
            if not target.is_relative_to(self.root / "scratch"):
                raise ValueError("Scratch path escapes temporary storage")
            return str(target)
        return value

    def prepare(self, call, *, supports_cwd: bool = False):
        args = call.arguments
        if set(args) == {"arguments"} and isinstance(args["arguments"], dict):
            args = args["arguments"]
        if call.name in {"write_file", "edit_file", "read_file", "list_directory", "replace_file_content", "multi_replace_file_content"}:
            for key in ("file_path", "path", "target_file", "directory_path", "folder"):
                if isinstance(args.get(key), str):
                    args[key] = self.resolve(args[key])
        if call.name == "run_terminal_command" and supports_cwd and not args.get("working_directory"):
            command = str(args.get("command", args.get("cmd", "")))
            argv = args.get("argv") or []
            if re.search(r"(?:^|[\s\"'])\.?[/\\]?scratch[/\\]", command) or any(str(part).replace("\\", "/").startswith("scratch/") or self.owns(str(part)) for part in argv):
                args["working_directory"] = str(self.root)

    def instruction(self) -> str:
        return (
            f"\nTEMPORARY RESEARCH STORAGE: {self.root}. Disposable probes, scripts, screenshots, and raw extracts "
            "belong here. Relative scratch/... file paths are mapped here automatically; execute scratch scripts "
            "with working_directory set to this directory. Use absolute workspace paths for final deliverables. "
            "Read and extract needed evidence before finishing; this temporary directory is automatically deleted "
            "on success, failure, or interruption. Never use placeholder research data as evidence.\n"
        )

    def close(self):
        self._temporary.cleanup()
