from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from .state import MissionState, MissionStateMachine


@dataclass
class Mission:
    mission_id: str
    task_id: str
    request_id: str
    goal: str
    capability: str
    arguments: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    expected_result: dict[str, Any] = field(default_factory=dict)
    priority: str = "normal"
    state_machine: MissionStateMachine | None = None
    last_result: dict[str, Any] = field(default_factory=dict)

    def transition(self, state: MissionState, **payload: Any) -> None:
        if self.state_machine is None:
            self.state_machine = MissionStateMachine(self.task_id, self.request_id)
        self.state_machine.transition(state, **payload)


class MissionCoordinator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._missions: dict[str, Mission] = {}

    def create(
        self,
        *,
        goal: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        expected_result: dict[str, Any] | None = None,
        priority: str = "normal",
        request_id: str | None = None,
        task_id: str | None = None,
    ) -> Mission:
        task_id = task_id or f"TASK-{uuid.uuid4().hex[:10].upper()}"
        mission_id = f"MISSION-{uuid.uuid4().hex[:10].upper()}"
        mission = Mission(
            mission_id=mission_id,
            task_id=task_id,
            request_id=request_id or f"REQ-{uuid.uuid4().hex[:10].upper()}",
            goal=goal,
            capability=capability,
            arguments=arguments or {},
            constraints=constraints or {},
            expected_result=expected_result or {},
            priority=priority,
        )
        mission.transition(MissionState.CREATED, message=goal)
        with self._lock:
            self._missions[task_id] = mission
        return mission

    def get(self, task_id: str) -> Mission | None:
        with self._lock:
            return self._missions.get(task_id)

    def update_result(self, task_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            mission = self._missions.get(task_id)
            if not mission:
                return
            mission.last_result = dict(result)
            status = str(result.get("status", "")).lower()
            if status in {"success", "completed"} and result.get("verified", False):
                mission.transition(MissionState.COMPLETED, result=result)
            elif status in {"partial", "waiting"}:
                mission.transition(MissionState.PARTIAL, result=result)
            elif status in {"cancelled"}:
                mission.transition(MissionState.CANCELLED, result=result)
            else:
                mission.transition(MissionState.FAILED, result=result)

    def latest(self) -> Mission | None:
        with self._lock:
            values = list(self._missions.values())
            return values[-1] if values else None


_global_coordinator: MissionCoordinator | None = None


def get_mission_coordinator() -> MissionCoordinator:
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = MissionCoordinator()
    return _global_coordinator
