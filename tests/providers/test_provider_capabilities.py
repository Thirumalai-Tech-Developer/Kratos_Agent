"""Tests for AgentCapabilities, TaskRequirements, and scoring algorithms."""

import pytest
from kratos_agent.providers.base import AgentCapabilities
from kratos_agent.providers.capabilities import (
    TaskRequirements,
    evaluate_capability_match,
    score_provider,
)


def test_capabilities_property_aliases():
    caps = AgentCapabilities(
        tool_calling=True,
        sandbox=True,
        session_persistence=True,
        long_running=True,
    )
    assert caps.local_tools is True
    assert caps.sandboxing is True
    assert caps.persistent_sessions is True
    assert caps.long_running_runtime is True


def test_capability_matching_strict():
    caps = AgentCapabilities(
        streaming=True,
        image_input=False,
        tool_calling=True,
    )

    req_ok = TaskRequirements(requires_streaming=True, requires_tools=True)
    assert evaluate_capability_match(caps, req_ok) is True

    req_fail = TaskRequirements(requires_vision=True)
    assert evaluate_capability_match(caps, req_fail) is False


def test_score_provider_transparent_reasons():
    caps = AgentCapabilities(
        streaming=True,
        image_input=True,
        tool_calling=True,
        steering=True,
        interruption=True,
    )
    reqs = TaskRequirements(
        requires_streaming=True,
        requires_vision=True,
        requires_steering=True,
    )

    score, reasons = score_provider("codex", caps, reqs)
    assert score > 0.0
    assert any("vision" in r.lower() for r in reasons)
    assert any("streaming" in r.lower() for r in reasons)
    assert any("interactive turn steering" in r.lower() for r in reasons)
