from __future__ import annotations

from typing import Any

from kratos_agent.capabilities.registry import get_capability_registry
from kratos_agent.semantic.schemas import MissionIntent


def build_execution_plan(intent: MissionIntent) -> list[dict[str, Any]]:
    capability = intent.capability
    if capability and get_capability_registry().validate(capability):
        return [{"capability": capability, "arguments": intent.arguments, "expected_result": intent.expected_result}]
    return [{"capability": None, "mission": intent.goal, "arguments": intent.arguments}]
