from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SessionMemory:
    session_id: str
    turns: List[Dict[str, Any]] = field(default_factory=list)
    current_mission: Dict[str, Any] | None = None
    current_task: Dict[str, Any] | None = None

    def context(self, max_turns: int = 8) -> List[Dict[str, Any]]:
        return list(self.turns[-max_turns:])
