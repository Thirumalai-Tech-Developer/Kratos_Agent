"""Provider-neutral contracts for the Kratos agent runtime.

These objects are intentionally free of CLI, LangChain, and provider imports.  The
runtime persists them as JSON events, making a turn inspectable and recoverable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional
import time
import uuid


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


@dataclass
class ChatMessage:
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
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
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Dict[str, int] = field(default_factory=dict)
    raw: Any = None


@dataclass
class RuntimeEvent:
    kind: EventKind
    payload: Dict[str, Any] = field(default_factory=dict)
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
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
    parameters: Dict[str, Any]
    permission: ToolPermission
    timeout_seconds: int = 300
    source: str = "builtin"


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
