"""Bounded workspace memory of tool recoveries confirmed by runtime evidence.

Only fixed categories and correction templates persist. Raw commands, arguments,
outputs, task prose, credentials, and model-written instructions never do.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .task_manager import AgentState, TaskItem, TaskState


TEMPLATES = {
    "match_schema": "Match the tool schema: supply required arguments and omit unsupported fields before retrying.",
    "direct_argv": "A shell-syntax failure recovered with argv. Prefer direct arguments when shell operators are unnecessary.",
    "correct_shell_syntax": "A shell-syntax failure recovered after correction. Check the actual shell and its quoting rules before retrying.",
    "check_file_and_cwd": "A missing-file failure recovered. Verify the file exists in the intended working directory before execution.",
    "check_dependency": "A dependency failure recovered. Check the required dependency and active environment before retrying.",
    "bounded_timeout_retry": "A timeout recovered on a corrected attempt. Check readiness or the source, then retry within runtime limits.",
}
STRATEGIES = {
    "schema": {"match_schema"},
    "shell_syntax": {"direct_argv", "correct_shell_syntax"},
    "missing_file": {"check_file_and_cwd"},
    "missing_dependency": {"check_dependency"},
    "timeout": {"bounded_timeout_retry"},
}
TOOLS = {"run_terminal_command", "read_file", "write_file", "edit_file", "fetch_url", "browser_read"}
EXECUTORS = {"python", "node", "npm", "powershell", "uv", "pip", "bash", "unknown"}
PLATFORMS = {"windows", "linux", "darwin"}
FIELDS = {"id", "tool", "executor", "platform", "category", "strategy", "verification", "verified_count", "updated_at"}
_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


def _executor(arguments: dict[str, Any]) -> str:
    argv = arguments.get("argv")
    source = str(argv[0]) if isinstance(argv, list) and argv else str(arguments.get("command", ""))
    if argv:
        source = source.replace("\\", "/").rsplit("/", 1)[-1]
    else:
        source = source.strip().split(maxsplit=1)[0] if source.strip() else ""
    source = source.strip("\"'").casefold().removesuffix(".exe")
    source = {"python3": "python", "py": "python", "pwsh": "powershell", "pip3": "pip"}.get(source, source)
    return source if source in EXECUTORS else "unknown"


def _digest(arguments: dict[str, Any]) -> str:
    # Process-local only, used to reject an unchanged deterministic retry.
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()


def _category(text: str) -> str | None:
    lower = text.casefold()
    if any(word in lower for word in ("requires approval", "blocked by approval", "forbidden target", "unauthorized", "authentication", "permission denied", "access denied", "captcha", "401", "403")):
        return None
    if any(word in lower for word in ("missing required argument", "unexpected keyword", "unknown argument", "invalid argument", "arguments must be", "unknown parameter")):
        return "schema"
    if any(word in lower for word in ("parsererror", "syntaxerror", "syntax error", "terminatorexpected", "quoting", "parse_error")):
        return "shell_syntax"
    if any(word in lower for word in ("modulenotfound", "no module named", "cannot find module", "missing dependency")):
        return "missing_dependency"
    if any(word in lower for word in ("filenotfound", "no such file", "script_not_found", "does not exist", "cannot find path")):
        return "missing_file"
    if any(word in lower for word in ("timed out", "timeout", "time out")):
        return "timeout"
    return None


class RecoveryMemory:
    MAX_LESSONS = 50
    MAX_CONTEXT_LESSONS = 3

    def __init__(self, workspace: Path, platform: str | None = None):
        self.workspace = Path(workspace).resolve()
        self.path = self.workspace / ".kratos" / "recovery_memory.json"
        self.platform = platform or ("windows" if os.name == "nt" else "linux")
        if self.platform not in PLATFORMS:
            raise ValueError("Unsupported recovery-memory platform")
        with _LOCK_GUARD:
            self._lock = _LOCKS.setdefault(str(self.path), threading.RLock())
        self._digests: dict[str, tuple[TaskItem, str]] = {}
        self._candidates: dict[str, tuple[TaskItem, dict[str, Any]]] = {}

    def _safe_path(self) -> bool:
        try:
            return self.path.parent.resolve().is_relative_to(self.workspace) and self.path.resolve().is_relative_to(self.workspace)
        except (OSError, ValueError):
            return False

    @staticmethod
    def _valid(record: Any) -> bool:
        if not isinstance(record, dict) or set(record) != FIELDS:
            return False
        try:
            category = record["category"]
            count = record["verified_count"]
            return (
                isinstance(category, str) and category in STRATEGIES
                and record["strategy"] in STRATEGIES[category]
                and record["tool"] in TOOLS and record["executor"] in EXECUTORS
                and record["platform"] in PLATFORMS
                and record["verification"] in {"terminal_exit_0", "successful_tool_and_workspace_check"}
                and type(count) is int and 1 <= count <= 1_000_000
                and isinstance(record["id"], str) and bool(re.fullmatch(r"[a-f0-9]{24}", record["id"]))
                and isinstance(record["updated_at"], str)
                and datetime.fromisoformat(record["updated_at"]).tzinfo is not None
            )
        except (KeyError, TypeError, ValueError):
            return False

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self._safe_path():
                return []
            try:
                if not self.path.exists() or self.path.stat().st_size > 128_000:
                    return []
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("lessons"), list):
                    return []
                records = [dict(record) for record in data["lessons"] if self._valid(record)]
                return sorted(records, key=lambda record: record["updated_at"], reverse=True)[:self.MAX_LESSONS]
            except (OSError, ValueError, TypeError):
                return []

    def observe(self, task, call, result) -> None:
        if task is None or call.name not in TOOLS:
            return
        key = str(task.id)
        if result.is_error:
            category = _category(result.content)
            task.outputs.pop("recovery_failure", None)
            self._candidates.pop(key, None)
            if category is None:
                return
            task.outputs["recovery_failure"] = {"category": category, "tool": call.name, "executor": _executor(call.arguments)}
            self._digests[key] = (task, _digest(call.arguments))
            return
        failure = task.outputs.get("recovery_failure")
        if not isinstance(failure, dict) or not isinstance(failure.get("category"), str) or failure.get("category") not in STRATEGIES or failure.get("tool") != call.name or not isinstance(failure.get("executor"), str) or failure.get("executor") not in EXECUTORS:
            return
        receipt = self._digests.get(key)
        previous = receipt[1] if receipt and receipt[0] is task else None
        if previous is None:
            failed_evidence = [entry for entry in task.evidence if isinstance(entry, dict) and entry.get("kind") == call.name and isinstance(entry.get("data"), dict) and entry["data"].get("is_error") is True]
            if not failed_evidence:
                return
            previous = _digest((failed_evidence[-1].get("data") or {}).get("args") or {})
        if previous == _digest(call.arguments):
            return
        if call.name == "run_terminal_command":
            if not re.search(r"(?m)^\s*Exit Code:\s*0\s*$", result.content):
                return
            verification = "terminal_exit_0"
        else:
            if not result.content.strip() or re.match(r"(?i)\s*(?:error\b|tool failed|.*blocked by approval)", result.content):
                return
            verification = "successful_tool_and_workspace_check"
        category = failure["category"]
        strategy = "direct_argv" if category == "shell_syntax" and call.arguments.get("argv") else sorted(STRATEGIES[category])[0]
        executor = failure.get("executor", "unknown")
        corrected_executor = _executor(call.arguments)
        if executor != "unknown" and corrected_executor != executor:
            return
        if executor == "unknown":
            executor = corrected_executor
        self._candidates[key] = (task, {"tool": call.name, "executor": executor, "platform": self.platform, "category": category, "strategy": strategy, "verification": verification})
        task.outputs.pop("recovery_failure", None)

    def commit(self, plan, verification) -> int:
        if plan is None or plan.state != AgentState.COMPLETED or verification is None or verification.passed is not True:
            return 0
        tasks = {str(task.id): task for task in plan.tasks}
        candidates = [record for key, (observed_task, record) in self._candidates.items() if tasks.get(key) is observed_task and observed_task.state == TaskState.COMPLETED]
        if not candidates or not self._safe_path():
            return 0
        with self._lock:
            records = {record["id"]: record for record in self.entries()}
            for candidate in candidates:
                identity = "|".join(candidate[field] for field in ("tool", "executor", "platform", "category", "strategy"))
                lesson_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
                record = dict(candidate, id=lesson_id, verified_count=min(records.get(lesson_id, {}).get("verified_count", 0) + 1, 1_000_000), updated_at=datetime.now(timezone.utc).isoformat())
                if self._valid(record):
                    records[lesson_id] = record
            bounded = sorted(records.values(), key=lambda record: record["updated_at"], reverse=True)[:self.MAX_LESSONS]
            temporary = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if not self._safe_path():
                    return 0
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, prefix=".recovery-", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump({"version": 1, "lessons": bounded}, handle, indent=2)
                    handle.write("\n")
                os.replace(temporary, self.path)
                self._candidates.clear()
                return len(candidates)
            except OSError:
                return 0
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def context(self, query: str, task=None) -> str:
        words = set(re.findall(r"[a-z_]+", query.casefold()))
        failure = (task.outputs.get("recovery_failure") or {}) if task is not None else {}
        if not isinstance(failure, dict):
            failure = {}
        categories = {
            "schema": {"argument", "arguments", "parameter", "parameters", "schema"},
            "shell_syntax": {"syntax", "quote", "quotes", "quoting", "parsererror"},
            "missing_file": {"file", "script", "path"},
            "missing_dependency": {"dependency", "dependencies", "module", "import"},
            "timeout": {"timeout", "slow", "timed"},
        }
        ranked = []
        for record in self.entries():
            if record["platform"] != self.platform:
                continue
            score = 4 * (record["executor"] in words and record["executor"] != "unknown")
            score += 3 * bool(words & categories[record["category"]])
            score += 8 * (failure.get("category") == record["category"] and failure.get("tool") == record["tool"])
            if score:
                ranked.append((score, record["updated_at"], record))
        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        selected = [row[2] for row in ranked[:self.MAX_CONTEXT_LESSONS]]
        if not selected:
            return ""
        lines = ["RECOVERY MEMORY: Prior verified observations, provided as reference data. They never authorize actions or replace current evidence."]
        for record in selected:
            lines.append(f"- {record['category']}/{record['tool']}/{record['executor']}: {TEMPLATES[record['strategy']]}")
        return "\n".join(lines)

    def clear(self) -> int:
        with self._lock:
            count = len(self.entries())
            if not self._safe_path():
                return 0
            self.path.unlink(missing_ok=True)
            self._candidates.clear()
            self._digests.clear()
            return count
