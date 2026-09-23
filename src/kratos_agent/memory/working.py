"""Working Memory: Ephemeral state container for the active task."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContinuationState:
    """Persistent task continuation state across sequential commands (§21, §22, §23, §24)."""
    task_id: str = ""
    objective: str = ""
    active_browser_target: Optional[Any] = None
    current_step: str = ""
    completed_steps: List[str] = field(default_factory=list)
    last_action: Optional[str] = None
    last_result: Optional[str] = None
    verified_state: Dict[str, Any] = field(default_factory=dict)
    interrupted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "active_browser_target": self.active_browser_target.to_dict() if self.active_browser_target and hasattr(self.active_browser_target, "to_dict") else None,
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "last_action": self.last_action,
            "last_result": self.last_result,
            "verified_state": self.verified_state,
            "interrupted": self.interrupted,
        }


@dataclass
class WorkingMemory:
    """Working memory contains ONLY the active task state (§21)."""
    goal: str = ""
    current_step: int = 0
    active_application: Optional[str] = None
    known_elements: List[Dict[str, Any]] = field(default_factory=list)
    temporary_variables: Dict[str, Any] = field(default_factory=dict)
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)
    continuation: Optional[ContinuationState] = None

    def record_action(self, action: str, result: str, ok: bool = True) -> None:
        self.recent_actions.append({"action": action, "result": result, "ok": ok})
        if len(self.recent_actions) > 10:
            self.recent_actions.pop(0)

    def set_variable(self, key: str, value: Any) -> None:
        self.temporary_variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        return self.temporary_variables.get(key, default)

    def set_continuation(self, state: ContinuationState) -> None:
        self.continuation = state

    def get_continuation(self) -> Optional[ContinuationState]:
        return self.continuation

    def clear_continuation(self) -> None:
        self.continuation = None

    def reset(self) -> None:
        self.goal = ""
        self.current_step = 0
        self.active_application = None
        self.known_elements.clear()
        self.temporary_variables.clear()
        self.recent_actions.clear()
        self.continuation = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "current_step": self.current_step,
            "active_application": self.active_application,
            "known_elements": self.known_elements,
            "temporary_variables": self.temporary_variables,
            "recent_actions": self.recent_actions,
            "continuation": self.continuation.to_dict() if self.continuation else None,
        }

