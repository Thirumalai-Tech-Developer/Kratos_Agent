"""User-facing event filter governing what reaches terminal and speech."""
from __future__ import annotations
from enum import Enum
from typing import Optional

from kratos_agent.events.models import AgentEvent, EventType
from kratos_agent.events.filters import is_user_visible


class OutputMode(str, Enum):
    NORMAL = "NORMAL"
    DEBUG = "DEBUG"
    SILENT = "SILENT"


class UserOutputFilter:
    """Controls event visibility based on the active output mode (§4, §5)."""

    def __init__(self, mode: OutputMode = OutputMode.NORMAL) -> None:
        self.mode = mode

    def should_display(self, event: AgentEvent) -> bool:
        if self.mode == OutputMode.DEBUG:
            return True
        if self.mode == OutputMode.SILENT:
            return event.type in (EventType.TASK_COMPLETED, EventType.TASK_FAILED)

        # NORMAL mode: only user-visible milestones and tasks
        return is_user_visible(event)

    def should_speak(self, event: AgentEvent) -> bool:
        if self.mode == OutputMode.SILENT:
            return False

        # Never speak debug, tool outputs, or internal actions (§6, §53)
        if event.type in (
            EventType.DEBUG,
            EventType.TOOL_OUTPUT,
            EventType.ACTION_STARTED,
            EventType.ACTION_COMPLETED,
            EventType.ACTION_FAILED,
            EventType.PLAN_CREATED,
            EventType.VERIFICATION_STARTED,
        ):
            return False

        # Only speak task start, key milestone, completed, and failed (§44)
        return event.type in (
            EventType.TASK_STARTED,
            EventType.MILESTONE,
            EventType.TASK_COMPLETED,
            EventType.TASK_FAILED,
        )


_user_output_filter: Optional[UserOutputFilter] = None


def get_user_output_filter() -> UserOutputFilter:
    global _user_output_filter
    if _user_output_filter is None:
        _user_output_filter = UserOutputFilter()
    return _user_output_filter
