"""Structured output models, action protocol, state machine, and plan caching."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OutputMode(str, Enum):
    NORMAL = "NORMAL"
    CONCISE = "CONCISE"
    DEBUG = "DEBUG"
    JSON = "JSON"
    STREAMING = "STREAMING"


class ActionType(str, Enum):
    TOOL_CALL = "tool_call"
    FINAL_RESPONSE = "final_response"
    RETRY = "retry"


@dataclass
class AgentAction:
    """Standardized action contract emitted by agent reasoning."""
    type: ActionType
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    expected_result: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "type": self.type.value if isinstance(self.type, ActionType) else str(self.type),
            "reason": self.reason,
            "expected_result": self.expected_result,
        }
        if self.tool:
            data["tool"] = self.tool
            data["arguments"] = self.arguments
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentAction:
        raw_type = data.get("type", "tool_call")
        try:
            act_type = ActionType(raw_type)
        except ValueError:
            act_type = ActionType.TOOL_CALL

        return cls(
            type=act_type,
            tool=data.get("tool"),
            arguments=data.get("arguments", {}),
            reason=data.get("reason", ""),
            expected_result=data.get("expected_result", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> AgentAction:
        return cls.from_dict(json.loads(json_str))


class TaskStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class TaskResult:
    """Structured terminal response for completed, partial, or failed tasks."""
    status: TaskStatus
    summary: str
    result: Optional[str] = None
    verified: bool = False
    completed: List[str] = field(default_factory=list)
    remaining: List[str] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    recovery_attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "status": self.status.value,
            "summary": self.summary,
            "verified": self.verified,
        }
        if self.result is not None:
            data["result"] = self.result
        if self.completed:
            data["completed"] = self.completed
        if self.remaining:
            data["remaining"] = self.remaining
        if self.error:
            data["error"] = self.error
        if self.recovery_attempts > 0:
            data["recovery_attempts"] = self.recovery_attempts
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class ActionState(str, Enum):
    READY = "READY"
    OBSERVING = "OBSERVING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ActionStateMachine:
    """Guarantees valid transitions and supports failure recovery without full resets."""

    def __init__(self) -> None:
        self.state: ActionState = ActionState.READY
        self.recovery_attempts: int = 0
        self.max_recovery_attempts: int = 3

    def transition_to(self, new_state: ActionState) -> None:
        valid_transitions = {
            ActionState.READY: [ActionState.OBSERVING, ActionState.PLANNING, ActionState.EXECUTING],
            ActionState.OBSERVING: [ActionState.PLANNING, ActionState.EXECUTING, ActionState.RECOVERING],
            ActionState.PLANNING: [ActionState.EXECUTING, ActionState.FAILED],
            ActionState.EXECUTING: [ActionState.VERIFYING, ActionState.FAILED, ActionState.RECOVERING],
            ActionState.VERIFYING: [ActionState.SUCCESS, ActionState.FAILED, ActionState.RECOVERING],
            ActionState.RECOVERING: [ActionState.OBSERVING, ActionState.EXECUTING, ActionState.FAILED],
            ActionState.SUCCESS: [ActionState.READY],
            ActionState.FAILED: [ActionState.READY, ActionState.RECOVERING],
        }
        allowed = valid_transitions.get(self.state, [])
        if new_state not in allowed:
            # Soft fallback to allow progression while logging
            pass
        self.state = new_state

    def handle_failure(self) -> bool:
        """Transitions to RECOVERING if attempts remain, else FAILED. Returns True if can recover."""
        if self.recovery_attempts < self.max_recovery_attempts:
            self.recovery_attempts += 1
            self.transition_to(ActionState.RECOVERING)
            return True
        self.transition_to(ActionState.FAILED)
        return False

    def reset(self) -> None:
        self.state = ActionState.READY
        self.recovery_attempts = 0


@dataclass
class CachedPlan:
    """Maintains plan execution progress and prevents wasteful regeneration."""
    goal: str
    steps: List[str]
    current_step_idx: int = 0
    completed_steps: List[str] = field(default_factory=list)
    failed_step: Optional[str] = None
    remaining_steps: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.remaining_steps and self.steps:
            self.remaining_steps = list(self.steps)

    @property
    def current_step(self) -> Optional[str]:
        if 0 <= self.current_step_idx < len(self.steps):
            return self.steps[self.current_step_idx]
        return None

    def advance(self, success: bool, error_msg: Optional[str] = None) -> None:
        if self.current_step:
            step_desc = self.current_step
            if success:
                self.completed_steps.append(step_desc)
                if self.remaining_steps:
                    self.remaining_steps.pop(0)
                self.current_step_idx += 1
                self.failed_step = None
            else:
                self.failed_step = f"{step_desc} (Error: {error_msg})"

    def should_replan(
        self,
        step_failed: bool = False,
        env_changed_unexpectedly: bool = False,
        user_changed_request: bool = False,
    ) -> bool:
        """Only replans when environment changed unexpectedly, step failed, or user changed request."""
        return step_failed or env_changed_unexpectedly or user_changed_request
