"""
Event Contract Normalization for Omni/SSE streaming.
"""
import json
from dataclasses import dataclass
from typing import Any

from .runtime_contracts import RuntimeEvent


@dataclass
class AgentEvent:
    event_id: str
    event_type: str
    payload: dict[str, Any]

    @classmethod
    def from_runtime(cls, rev: RuntimeEvent) -> 'AgentEvent':
        return cls(
            event_id=rev.turn_id,
            event_type=rev.kind.value,
            payload=rev.payload
        )

    def to_sse(self) -> str:
        """Serialize to Server-Sent Event string, supporting Last-Event-ID."""
        data_str = json.dumps(self.payload, default=str)
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {data_str}\n\n"
