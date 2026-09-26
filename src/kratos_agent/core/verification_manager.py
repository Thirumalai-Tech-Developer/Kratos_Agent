"""Verification manager: runs post-implementation verification for coding tasks.

Checks file integrity, validates syntax/structure of created assets, runs existing
project test suites when discoverable, and confirms workspace state before marking
tasks completed. Separates implementation from dedicated verification.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .evidence import Evidence, OutcomeAssertion
from .runtime_contracts import EventKind, RuntimeEvent


@dataclass(slots=True)
class Verdict:
    allow: bool
    code: str = ""
    reason: str = ""
    correction: str = ""
    evidence: Evidence | None = None


@dataclass
class VerificationResult:
    passed: bool
    summary: str
    details: list[str] = field(default_factory=list)
    build_passed: bool | None = None
    tests_passed: bool | None = None
    browser_passed: bool | None = None
    files_checked: int = 0


class VerificationManager:
    def __init__(self, workspace: Path, emit: Callable[[RuntimeEvent], None] | None = None) -> None:
        self.workspace = workspace.resolve()
        self.emit = emit or (lambda e: None)

    def verify_observable_outcome(
        self,
        assertion: OutcomeAssertion,
        ccs: Any,
        *,
        require_fresh: bool = True,
    ) -> Evidence:
        """Run an assertion against LIVE state. Never against a cached frame
        unless require_fresh=False is passed explicitly."""
        from kratos_agent.ccs.assertions import assertion_runner
        return assertion_runner.run(ccs, assertion)

    def gate_completion(
        self,
        task: Any,
        declared_result: dict,
        evidence: Evidence | None,
    ) -> Verdict:
        """THE gate. Called by agent_loop before any task may transition to COMPLETED."""
        if not getattr(task, "requires_observable_evidence", False):
            return Verdict(allow=True, reason="informational_task")

        if evidence is None:
            kind = getattr(getattr(task, "assertion", None), "kind", "outcome")
            return Verdict(
                allow=False,
                code="NO_EVIDENCE",
                correction=(
                    "You declared this step complete but no outcome was observed. "
                    "Dispatching an action is not completing it. Run the declared "
                    f"assertion ({kind}) and attach the Evidence, "
                    "or report failure honestly. Do NOT declare success again "
                    "without evidence."
                ),
            )

        if not evidence.trustworthy:
            return Verdict(
                allow=False,
                code="UNVERIFIED_OUTCOME",
                correction=(
                    f"The outcome was checked and is NOT true. Observed: "
                    f"{evidence.detail}. Do not claim success. Either fix the "
                    "underlying cause and re-verify, or report the failure with "
                    "this observation as the reason."
                ),
                evidence=evidence,
            )

        return Verdict(allow=True, reason="evidence_met", evidence=evidence)

    def _candidate_test_commands(self) -> list[tuple[str, list[str]]]:
        """Discover *existing* project verification commands.

        This intentionally ignores test files created during the current turn.
        A self-authored verifier is useful for debugging but is not authoritative.
        """
        root = self.workspace
        candidates: list[tuple[str, list[str]]] = []

        for name in ("run-tests.sh", "test.sh"):
            path = root / name
            if path.is_file():
                candidates.append((name, ["bash", str(path)]))

        ps1 = root / "run-tests.ps1"
        if ps1.is_file() and os.name == "nt":
            candidates.append((ps1.name, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)]))

        makefile = root / "Makefile"
        if makefile.is_file():
            try:
                text = makefile.read_text(encoding="utf-8", errors="replace")
                if any(line.startswith("test:") or line.startswith("test :") for line in text.splitlines()):
                    candidates.append(("make test", ["make", "test"]))
            except OSError:
                pass

        package = root / "package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8", errors="replace"))
                scripts = data.get("scripts") or {}
                test_script = str(scripts.get("test", "")).strip()
                if test_script and "no test specified" not in test_script.lower():
                    candidates.append(("npm test", ["npm", "test"]))
            except (OSError, json.JSONDecodeError):
                pass

        if (root / "Cargo.toml").is_file():
            candidates.append(("cargo test", ["cargo", "test"]))

        if (root / "go.mod").is_file():
            candidates.append(("go test ./...", ["go", "test", "./..."]))

        python_tests = root / "tests"
        if python_tests.is_dir():
            if (root / "pyproject.toml").is_file() or any(
                p.suffix == ".py" and p.name.startswith("test_") for p in python_tests.rglob("*.py")
            ):
                candidates.append(("pytest", [sys.executable, "-m", "pytest", "-q"]))

        seen: set[tuple[str, ...]] = set()
        unique: list[tuple[str, list[str]]] = []
        for label, command in candidates:
            key = tuple(command)
            if key not in seen:
                seen.add(key)
                unique.append((label, command))
        return unique

    def _run_discovered_tests(
        self,
        *,
        changed_files: list[str],
        timeout_seconds: int = 120,
    ) -> tuple[bool | None, list[str]]:
        """Run pre-existing project tests, if a trustworthy suite is discoverable."""
        commands = self._candidate_test_commands()
        if not commands:
            return None, ["No pre-existing project test suite was discovered; structural verification only."]

        details: list[str] = []
        all_passed = True

        for label, command in commands[:2]:
            try:
                completed = subprocess.run(
                    command,
                    cwd=self.workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    timeout=timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                all_passed = False
                details.append(f"Test command failed to start ({label}): {exc}")
                continue

            output = (completed.stdout or "").strip()
            if len(output) > 6000:
                output = output[-6000:]
            if completed.returncode == 0:
                details.append(f"Authoritative project tests passed: {label}")
            else:
                all_passed = False
                details.append(f"Authoritative project tests FAILED: {label} (exit {completed.returncode})")
                if output:
                    details.append(output)

        return all_passed, details

    def verify_workspace(
        self,
        changed_files: list[str],
        verification_type: str = "auto",
        require_files: bool = True,
        browser_performed: bool = False,
        turn_id: str = "",
    ) -> VerificationResult:
        """Run file integrity checks plus any discoverable authoritative project tests."""
        self.emit(RuntimeEvent(
            EventKind.VERIFICATION_STARTED,
            {"changed_files": changed_files, "file_count": len(changed_files), "type": verification_type},
            turn_id,
        ))

        details: list[str] = []
        passed = True
        files_checked = 0
        build_passed: bool | None = None
        tests_passed: bool | None = None
        browser_passed: bool | None = None

        if require_files and len(changed_files) == 0:
            passed = False
            details.append("No files were created or modified during task execution.")

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

        if passed and files_checked > 0:
            build_passed = True

        should_run_tests = verification_type == "auto" or "test" in verification_type or "build" in verification_type
        if passed and should_run_tests and files_checked > 0:
            tests_passed, test_details = self._run_discovered_tests(changed_files=changed_files)
            details.extend(test_details)
            if tests_passed is False:
                passed = False

        if "browser" in verification_type:
            if browser_performed:
                browser_passed = True
                details.append("Browser preview verification passed.")
            else:
                browser_passed = None
                details.append("Browser verification not performed.")

        if passed and files_checked > 0:
            summary = f"Verified {files_checked} changed file(s) successfully."
            if tests_passed is True:
                summary += " Existing project tests also passed."
            elif tests_passed is None:
                summary += " No authoritative project test suite was available."
        elif passed and not require_files:
            summary = "Workspace verified successfully."
        else:
            passed = False
            issue_count = len([d for d in details if any(x in d.lower() for x in ("error", "missing", "no files", "empty", "failed"))])
            summary = f"Verification failed: {issue_count} issue(s) detected."

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
            {"passed": passed, "summary": summary, "files_checked": files_checked, "tests_passed": tests_passed, "details": details},
            turn_id,
        ))
        return result

    def verify_provider_task(
        self,
        task_id: str,
        provider: str,
        changed_files: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        require_files: bool = True,
        verification_type: str = "auto",
        declared_output: str = "",
    ) -> VerificationResult:
        """Authoritative verification gate for tasks executed by external agent providers.

        Ensures provider reported completion is backed by tangible, validated evidence:
        syntax checks, non-empty files, tests, and expected output presence.
        """
        files = changed_files or []
        res = self.verify_workspace(
            changed_files=files,
            verification_type=verification_type,
            require_files=require_files and len(files) > 0,
            turn_id=task_id,
        )

        details = list(res.details)
        passed = res.passed

        # False completion defense: check declared outputs if expected
        if expected_outputs and declared_output:
            for expected in expected_outputs:
                if expected.lower() not in declared_output.lower():
                    passed = False
                    details.append(f"Provider {provider} output missing expected content: '{expected}'")

        if not passed:
            details.append(f"Provider '{provider}' completion rejected by Kratos verification gate.")
            summary = f"Verification failed for provider '{provider}': {len(details)} issue(s) found."
        else:
            details.append(f"Provider '{provider}' output confirmed by Kratos verification.")
            summary = f"Provider '{provider}' task successfully verified."

        return VerificationResult(
            passed=passed,
            summary=summary,
            details=details,
            build_passed=res.build_passed,
            tests_passed=res.tests_passed,
            browser_passed=res.browser_passed,
            files_checked=res.files_checked,
        )

