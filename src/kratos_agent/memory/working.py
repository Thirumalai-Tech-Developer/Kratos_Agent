"""Working Memory: Ephemeral state container for the active task."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContinuationState:
    """Persistent task continuation state across sequential commands (§21, §22, §23, §24)."""
    task_id: str = ""
    objective: str = ""
    active_browser_target: Any | None = None
    current_step: str = ""
    completed_steps: list[str] = field(default_factory=list)
    last_action: str | None = None
    last_result: str | None = None
    verified_state: dict[str, Any] = field(default_factory=dict)
    interrupted: bool = False

    def to_dict(self) -> dict[str, Any]:
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
    """Working memory contains ONLY the active task state and compacted history (§30, §34)."""
    goal: str = ""
    current_task: str | None = None
    current_state: str = "IDLE"
    active_application: str | None = None
    current_browser_tab: str | None = None
    last_observation: str = ""
    current_step: int = 0
    known_elements: list[dict[str, Any]] = field(default_factory=list)
    temporary_variables: dict[str, Any] = field(default_factory=dict)
    recent_actions: list[dict[str, Any]] = field(default_factory=list)
    completed_task_summaries: list[dict[str, Any]] = field(default_factory=list)
    continuation: ContinuationState | None = None

    def record_action(self, action: str, result: str, ok: bool = True) -> None:
        self.recent_actions.append({"action": action, "result": result, "ok": ok})
        if len(self.recent_actions) > 10:
            self.recent_actions.pop(0)

    def compact_completed_task(
        self,
        task_title: str,
        success: bool,
        verification: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Automatically compresses completed task history to prevent context explosion (§34)."""
        summary = {
            "task": task_title,
            "result": "Successful" if success else "Failed",
            "verification": verification,
            "details": details or {},
        }
        self.completed_task_summaries.append(summary)
        # Keep maximum 5 compacted tasks in active working memory
        if len(self.completed_task_summaries) > 5:
            self.completed_task_summaries.pop(0)
        return summary

    def set_variable(self, key: str, value: Any) -> None:
        self.temporary_variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        return self.temporary_variables.get(key, default)

    def set_continuation(self, state: ContinuationState) -> None:
        self.continuation = state

    def get_continuation(self) -> ContinuationState | None:
        return self.continuation

    def clear_continuation(self) -> None:
        self.continuation = None

    def reset(self) -> None:
        self.goal = ""
        self.current_task = None
        self.current_state = "IDLE"
        self.active_application = None
        self.current_browser_tab = None
        self.last_observation = ""
        self.current_step = 0
        self.known_elements.clear()
        self.temporary_variables.clear()
        self.recent_actions.clear()
        self.completed_task_summaries.clear()
        self.continuation = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "current_task": self.current_task,
            "current_state": self.current_state,
            "active_application": self.active_application,
            "current_browser_tab": self.current_browser_tab,
            "last_observation": self.last_observation,
            "current_step": self.current_step,
            "known_elements": self.known_elements,
            "temporary_variables": self.temporary_variables,
            "recent_actions": self.recent_actions,
            "completed_task_summaries": self.completed_task_summaries,
            "continuation": self.continuation.to_dict() if self.continuation else None,
        }

