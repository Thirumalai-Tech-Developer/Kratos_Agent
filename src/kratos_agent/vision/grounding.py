from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GroundingTarget:
    target: str
    backend: str
    element: Any = None
    confidence: float = 0.0


class GroundingEngine:
    def resolve(self, target: dict[str, Any]) -> GroundingTarget | None:
        try:
            from kratos_agent.computer.gui.resolver import get_resolver
            element = get_resolver().resolve(target)
            if element:
                return GroundingTarget(str(target.get("name") or target.get("text") or ""), element.backend, element, 1.0)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
        return None
