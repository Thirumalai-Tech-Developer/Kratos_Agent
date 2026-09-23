from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorrelationIds:
    request_id: str
    turn_id: str
    task_id: str
    action_id: str
    tool_call_id: str

    @classmethod
    def create(cls, request_id: str | None = None, turn_id: str | None = None, task_id: str | None = None) -> "CorrelationIds":
        return cls(
            request_id=request_id or f"REQ-{uuid.uuid4().hex[:10].upper()}",
            turn_id=turn_id or f"TURN-{uuid.uuid4().hex[:10].upper()}",
            task_id=task_id or f"TASK-{uuid.uuid4().hex[:10].upper()}",
            action_id=f"ACT-{uuid.uuid4().hex[:10].upper()}",
            tool_call_id=f"TOOL-{uuid.uuid4().hex[:10].upper()}",
        )
