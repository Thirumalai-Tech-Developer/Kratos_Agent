from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMemory:
    session_id: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    current_mission: dict[str, Any] | None = None
    current_task: dict[str, Any] | None = None

    def context(self, max_turns: int = 8) -> list[dict[str, Any]]:
        return list(self.turns[-max_turns:])
