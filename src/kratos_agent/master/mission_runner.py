from __future__ import annotations

from typing import Any

from kratos_agent.orchestrator.mission import Mission, get_mission_coordinator
from kratos_agent.orchestrator.planner import build_execution_plan
from kratos_agent.orchestrator.state import MissionState


class MasterMissionRunner:
    """Structured mission coordinator used by the Master layer.

    Gemini supplies the mission semantics. This runner handles lifecycle only.
    """

    def start(
        self,
        *,
        goal: str,
        capability: str,
        arguments: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        expected_result: dict[str, Any] | None = None,
        priority: str = "normal",
        request_id: str | None = None,
    ) -> Mission:
        mission = get_mission_coordinator().create(
            goal=goal,
            capability=capability,
            arguments=arguments,
            constraints=constraints,
            expected_result=expected_result,
            priority=priority,
            request_id=request_id,
        )
        mission.transition(MissionState.ANALYZING, message="Structured mission received from Gemini.")
        build_execution_plan(
            type("Intent", (), {
                "capability": capability,
                "goal": goal,
                "arguments": arguments or {},
                "expected_result": expected_result or {},
            })()
        )
        mission.transition(MissionState.READY, message="Mission ready for Slave execution.")
        return mission
