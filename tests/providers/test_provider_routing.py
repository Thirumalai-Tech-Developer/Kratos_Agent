"""Tests for ProviderRouter decision logic, natural language parsing, and policies."""

import pytest
from kratos_agent.providers.capabilities import TaskRequirements
from kratos_agent.providers.router import (
    ExecutionMode,
    ProviderRouter,
    RoutingPolicy,
)


def test_natural_language_orchestration_parsing(mock_router):
    # Single provider
    res1 = mock_router.parse_natural_language_orchestration("Use Codex to implement the feature.")
    assert res1["primary_provider"] == "codex"
    assert res1["mode"] == ExecutionMode.SINGLE

    # Review mode
    res2 = mock_router.parse_natural_language_orchestration("Use Codex to code and Claude to review it.")
    assert res2["mode"] == ExecutionMode.REVIEW
    assert res2["primary_provider"] == "codex"
    assert "claude" in res2["reviewer_providers"]

    # Consensus mode
    res3 = mock_router.parse_natural_language_orchestration("Try two independent implementations and compare them.")
    assert res3["mode"] == ExecutionMode.CONSENSUS
    assert len(res3["consensus_providers"]) == 2


def test_select_provider_auto(mock_router):
    reqs = TaskRequirements(requires_reasoning=True, preferred_provider="mock_reasoning")
    decision = mock_router.select_provider("task-001", reqs)
    assert decision.selected_provider == "mock_reasoning"
    assert len(decision.reasoning_metadata) > 0


def test_select_provider_manual_override(mock_router):
    reqs = TaskRequirements()
    decision = mock_router.select_provider(
        task_id="task-002",
        requirements=reqs,
        requested_provider="mock_fast",
        policy=RoutingPolicy.MANUAL,
    )
    assert decision.selected_provider == "mock_fast"
