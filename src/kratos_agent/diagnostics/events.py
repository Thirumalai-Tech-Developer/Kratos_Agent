from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class DiagnosticEvent:
    name: str
    correlation: Dict[str, str]
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
