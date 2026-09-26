"""Provider-neutral contracts for the Kratos agent runtime.

These objects are intentionally free of CLI, LangChain, and provider imports.  The
runtime persists them as JSON events, making a turn inspectable and recoverable.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    # Lifecycle
    TURN_STARTED = "turn.started"
    AGENT_STARTED = "agent.started"
    UNDERSTANDING_STARTED = "understanding.started"
    PLANNING_STARTED = "planning.started"

    # Planning & Tasks
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_UPDATED = "task.updated"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_SKIPPED = "task.skipped"

    # Model & Context
    REQUEST_ASSEMBLED = "model.request_assembled"
    MODEL_THINKING = "model.thinking"
    MODEL_RESPONSE = "model.response"
    MODEL_CHUNK = "model.chunk"
    COMPACTED = "context.compacted"
    RETRY = "runtime.retry"

    # Tools & Execution
    TOOL_REQUESTED = "tool.requested"
    TOOL_CALL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

    # File & Command Events
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"
    FILE_DELETED = "file.deleted"
    FILE_INSPECTED = "file.inspected"
    COMMAND_STARTED = "command.started"
    COMMAND_COMPLETED = "command.completed"

    # Verification
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETED = "verification.completed"

    # Turn/Agent Completion & Interrupts
    AGENT_PAUSED = "agent.paused"
    AGENT_RESUMED = "agent.resumed"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"

    # Evidence & Verification Integrity (Defect Remediation)
    EVIDENCE = "evidence"
    FALSE_COMPLETION = "false_completion"
    RETRACTION = "retraction"
    DISPUTE = "dispute"
    PERF_WARNING = "perf_warning"
    BLOCKER_DETECTED = "blocker_detected"
    CAPABILITY = "capability"


class TerminalLatch:
    """A task emits exactly one terminal status. Ever."""

    def __init__(self, audit_recorder: Any = None):
        self._set: dict[str, str] = {}
        self._audit = audit_recorder

    def try_set(self, task_id: str, status: str) -> bool:
        prev = self._set.get(task_id)
        if prev is not None:
            import logging
            logging.getLogger("kratos.latch").error(
                "TERMINAL LATCH VIOLATION: task %s already %s, refused %s",
                task_id,
                prev,
                status,
            )
            if self._audit and hasattr(self._audit, "record"):
                self._audit.record(
                    kind="latch_violation",
                    task_id=task_id,
                    first=prev,
                    refused=status,
                )
            return False
        if status not in {"COMPLETED", "FAILED", "CANCELLED"}:
            return True  # non-terminal, always allowed
        self._set[task_id] = status
        return True


@dataclass
class ChatMessage:
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False
    truncated: bool = False
    duration_ms: int = 0


@dataclass
class ModelCapabilities:
    streaming: bool = True
    tool_calling: bool = True
    reasoning: bool = False
    vision: bool = False
    max_context_tokens: int = 128000


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None


@dataclass
class RuntimeEvent:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


class ToolPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    GIT = "git"
    NETWORK = "network"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    permission: ToolPermission
    timeout_seconds: int = 300
    source: str = "builtin"


@dataclass
class AgentRunState:
    run_id: str
    user_request: str
    workspace: Any
    target_dir: str | None = None
    target_deliverables: list[str] = field(default_factory=list)
    completed_tools: list[dict[str, Any]] = field(default_factory=list)
    inspected_files: list[str] = field(default_factory=list)
    written_files: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    phase: str = "planning"
    status: str = "running"
    start_time: float = field(default_factory=time.monotonic)

    def record_tool_call(self, name: str, args: dict[str, Any], is_error: bool = False) -> None:
        self.completed_tools.append({"name": name, "args": args, "is_error": is_error})

    def record_inspected_file(self, file_path: str) -> None:
        if file_path and file_path not in self.inspected_files:
            self.inspected_files.append(file_path)

    def record_written_file(self, file_path: str) -> None:
        if file_path and file_path not in self.written_files:
            self.written_files.append(file_path)

    def record_command(self, cmd: str) -> None:
        if cmd and cmd not in self.commands_run:
            self.commands_run.append(cmd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_request": self.user_request,
            "workspace": str(self.workspace),
            "target_dir": self.target_dir,
            "target_deliverables": list(self.target_deliverables),
            "completed_tools_count": len(self.completed_tools),
            "inspected_files": list(self.inspected_files),
            "written_files": list(self.written_files),
            "commands_run": list(self.commands_run),
            "phase": self.phase,
            "status": self.status,
            "elapsed_seconds": round(time.monotonic() - self.start_time, 2),
        }


def json_safe(value: Any) -> Any:
    """Convert runtime objects into JSON-safe values without serialising secrets."""
    if hasattr(value, "to_dict"):
        return json_safe(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
