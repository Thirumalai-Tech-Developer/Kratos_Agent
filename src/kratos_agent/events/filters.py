"""Event filtering predicates for separating internal actions from user progress."""
from __future__ import annotations
from kratos_agent.events.models import AgentEvent, EventType

USER_VISIBLE_EVENTS = {
    EventType.TASK_RECEIVED,
    EventType.TASK_STARTED,
    EventType.MILESTONE,
    EventType.TASK_COMPLETED,
    EventType.TASK_FAILED,
}

INTERNAL_EVENTS = {
    EventType.ACTION_STARTED,
    EventType.ACTION_COMPLETED,
    EventType.ACTION_FAILED,
    EventType.PLAN_CREATED,
    EventType.VERIFICATION_STARTED,
    EventType.VERIFICATION_COMPLETED,
    EventType.DEBUG,
    EventType.TOOL_OUTPUT,
}


def is_user_visible(event: AgentEvent) -> bool:
    """Returns True if the event should be shown to the user in normal mode (§4)."""
    return event.type in USER_VISIBLE_EVENTS


def is_internal(event: AgentEvent) -> bool:
    """Returns True if the event is an internal operational detail."""
    return event.type in INTERNAL_EVENTS


def is_milestone(event: AgentEvent) -> bool:
    """Returns True if the event represents an actionable milestone."""
    return event.type in (EventType.MILESTONE, EventType.TASK_COMPLETED, EventType.TASK_FAILED)
