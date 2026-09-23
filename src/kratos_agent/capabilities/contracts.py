from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class ActionEnvelope:
    task_id: str
    mission_id: str
    capability: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    preconditions: List[str] = field(default_factory=list)
    expected_state: Dict[str, Any] = field(default_factory=dict)
    verification_policy: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskResult:
    status: str
    task_id: str
    capability: str | None = None
    result: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: Dict[str, Any] | None = None
    verified: bool = False
