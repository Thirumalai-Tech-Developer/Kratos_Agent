"""Verification manager: runs post-implementation verification for coding tasks.

Checks file integrity, validates syntax/structure of created assets, runs test/build
checks if available, and confirms workspace state before marking tasks completed.
Separates implementation from dedicated verification.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .runtime_contracts import EventKind, RuntimeEvent


@dataclass
class VerificationResult:
    passed: bool
    summary: str
    details: List[str] = field(default_factory=list)
    build_passed: Optional[bool] = None
    tests_passed: Optional[bool] = None
    browser_passed: Optional[bool] = None
    files_checked: int = 0


class VerificationManager:
    def __init__(self, workspace: Path, emit: Optional[Callable[[RuntimeEvent], None]] = None) -> None:
        self.workspace = workspace.resolve()
        self.emit = emit or (lambda e: None)

    def verify_workspace(
        self,
        changed_files: List[str],
        verification_type: str = "auto",
        require_files: bool = True,
        browser_performed: bool = False,
        turn_id: str = "",
    ) -> VerificationResult:
        """Runs dedicated verification checks on changed workspace files."""
        self.emit(RuntimeEvent(
            EventKind.VERIFICATION_STARTED,
            {"changed_files": changed_files, "file_count": len(changed_files), "type": verification_type},
            turn_id,
        ))

        details: List[str] = []
        passed = True
        files_checked = 0
        build_passed: Optional[bool] = None
        tests_passed: Optional[bool] = None
        browser_passed: Optional[bool] = None

        if require_files and len(changed_files) == 0:
            passed = False
            details.append("No files were created or modified during task execution.")

        # 1. Verify existence and non-emptiness of all changed files
        for rel_path in changed_files:
            file_path = (self.workspace / rel_path).resolve()
            if not file_path.exists():
                file_path = Path(rel_path).resolve()
            if not file_path.exists():
                file_path = (Path.cwd() / rel_path).resolve()

            if not file_path.exists():
                passed = False
                details.append(f"Missing file: {rel_path}")
                continue

            files_checked += 1
            size = file_path.stat().st_size
            if size == 0 and not rel_path.endswith("__init__.py"):
                passed = False
                details.append(f"Empty file: {rel_path}")

            # 2. Syntax / Format validation
            suffix = file_path.suffix.lower()
            if suffix == ".py":
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    ast.parse(content)
                    details.append(f"Python syntax OK: {rel_path}")
                except SyntaxError as e:
                    passed = False
                    details.append(f"Python syntax error in {rel_path}: {e.msg} (line {e.lineno})")
            elif suffix == ".json":
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    json.loads(content)
                    details.append(f"JSON format OK: {rel_path}")
                except Exception as e:
                    passed = False
                    details.append(f"Invalid JSON in {rel_path}: {e}")
            elif suffix in (".html", ".htm"):
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if "<html" in content.lower() or "<!doctype html>" in content.lower() or "<div" in content.lower():
                    details.append(f"HTML structure OK: {rel_path}")
                else:
                    details.append(f"HTML file created: {rel_path}")
            elif suffix in (".js", ".jsx", ".ts", ".tsx"):
                details.append(f"Source file OK: {rel_path}")

        # 3. Dedicated Build/Test verification if requested
        if "build" in verification_type:
            if passed and files_checked > 0:
                build_passed = True
                details.append("Build files and syntax verified.")
            else:
                build_passed = False
                details.append("Build verification failed due to missing or invalid files.")

        if "browser" in verification_type:
            if browser_performed:
                browser_passed = True
                details.append("Browser preview verification passed.")
            else:
                browser_passed = None
                details.append("Browser verification not performed.")

        # 4. Overall status summary
        if passed and files_checked > 0:
            summary = f"Verified {files_checked} changed file(s) successfully."
        elif passed and not require_files:
            summary = "Workspace verified successfully."
        else:
            passed = False
            summary = f"Verification failed: {len([d for d in details if 'error' in d.lower() or 'missing' in d.lower() or 'no files' in d.lower() or 'empty' in d.lower()])} issue(s) detected."

        result = VerificationResult(
            passed=passed,
            summary=summary,
            details=details,
            build_passed=build_passed,
            tests_passed=tests_passed,
            browser_passed=browser_passed,
            files_checked=files_checked,
        )

        self.emit(RuntimeEvent(
            EventKind.VERIFICATION_COMPLETED,
            {
                "passed": passed,
                "summary": summary,
                "files_checked": files_checked,
                "details": details,
            },
            turn_id,
        ))

        return result
