from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from kratos_agent.events.bus import get_agent_event_bus
from kratos_agent.events.models import AgentEvent, EventType


class MissionState(str, Enum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    WAITING_FOR_CONTEXT = "WAITING_FOR_CONTEXT"
    WAITING_FOR_RESOURCE = "WAITING_FOR_RESOURCE"
    READY = "READY"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RETRYING = "RETRYING"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class MissionStateMachine:
    task_id: str
    request_id: str
    state: MissionState = MissionState.CREATED
    history: List[Dict[str, Any]] = field(default_factory=list)

    def transition(self, state: MissionState, *, message: str = "", **payload: Any) -> None:
        self.state = state
        event = AgentEvent(
            type=_event_for_state(state),
            task_id=self.task_id,
            message=message,
            payload={"state": state.value, **payload},
        )
        self.history.append(event.to_dict())
        get_agent_event_bus().emit(event)


def _event_for_state(state: MissionState) -> EventType:
    return {
        MissionState.ANALYZING: EventType.INTENT_RESOLVED,
        MissionState.PLANNING: EventType.PLAN_CREATED,
        MissionState.WAITING_FOR_CONTEXT: EventType.PRECONDITION_CHECK,
        MissionState.WAITING_FOR_RESOURCE: EventType.PRECONDITION_CHECK,
        MissionState.READY: EventType.PRECONDITION_CHECK,
        MissionState.EXECUTING: EventType.ACTION_STARTED,
        MissionState.VERIFYING: EventType.VERIFICATION_STARTED,
        MissionState.COMPLETED: EventType.TASK_COMPLETED,
        MissionState.FAILED: EventType.TASK_FAILED,
        MissionState.RETRYING: EventType.ACTION_RETRY,
        MissionState.REPLANNING: EventType.TASK_REPLANNED,
        MissionState.PARTIAL: EventType.ACTION_FAILED,
        MissionState.CANCELLED: EventType.TASK_FAILED,
    }.get(state, EventType.MILESTONE)
