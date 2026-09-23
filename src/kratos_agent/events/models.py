"""Structured event models for internal agent lifecycle and user-facing notifications."""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    TASK_RECEIVED = "task_received"
    INTENT_RESOLVED = "intent_resolved"
    CAPABILITY_SELECTED = "capability_selected"
    PRECONDITION_CHECK = "precondition_check"
    OBSERVATION_STARTED = "observation_started"
    OBSERVATION_COMPLETED = "observation_completed"
    PLAN_CREATED = "plan_created"
    TASK_STARTED = "task_started"
    PLAN_CREATED = "plan_created"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    ACTION_RETRY = "action_retry"
    TASK_REPLANNED = "task_replanned"
    USER_INPUT_REQUIRED = "user_input_required"
    MILESTONE = "milestone"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    DEBUG = "debug"
    TOOL_OUTPUT = "tool_output"


@dataclass
class AgentEvent:
    """Discrete event emitted during agent reasoning, execution, or verification."""
    type: EventType
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    source: str = "agent"
    task_id: Optional[str] = None
    turn_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type.value if isinstance(self.type, EventType) else str(self.type),
            "message": self.message,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "source": self.source,
            "task_id": self.task_id,
            "turn_id": self.turn_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentEvent:
        raw_type = data.get("type", "debug")
        try:
            evt_type = EventType(raw_type)
        except ValueError:
            evt_type = EventType.DEBUG

        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())[:8]),
            type=evt_type,
            message=data.get("message", ""),
            payload=data.get("payload", {}),
            timestamp=float(data.get("timestamp", time.time())),
            source=data.get("source", "agent"),
            task_id=data.get("task_id"),
            turn_id=data.get("turn_id"),
        )
