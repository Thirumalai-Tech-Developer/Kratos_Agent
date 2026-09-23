from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class PerceptionSnapshot:
    frame_id: str
    timestamp: float
    active_window: Dict[str, Any] = field(default_factory=dict)
    active_application: Dict[str, Any] = field(default_factory=dict)
    active_browser_tab: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
