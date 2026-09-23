from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class GroundingTarget:
    target: str
    backend: str
    element: Any = None
    confidence: float = 0.0


class GroundingEngine:
    def resolve(self, target: dict[str, Any]) -> Optional[GroundingTarget]:
        try:
            from kratos_agent.computer.gui.resolver import get_resolver
            element = get_resolver().resolve(target)
            if element:
                return GroundingTarget(str(target.get("name") or target.get("text") or ""), element.backend, element, 1.0)
        except Exception:
            pass
        return None
