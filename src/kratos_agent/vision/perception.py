from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PerceptionSnapshot:
    frame_id: str
    timestamp: float
    active_window: dict[str, Any] = field(default_factory=dict)
    active_application: dict[str, Any] = field(default_factory=dict)
    active_browser_tab: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
