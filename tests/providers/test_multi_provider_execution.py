"""Tests for coordinated multi-provider review and consensus workflows."""

import pytest
from kratos_agent.providers.mock import MockProvider
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.router import ProviderRouter


@pytest.mark.asyncio
async def test_multi_provider_review_workflow(tmp_path):
    reg = ProviderRegistry()

    # Coder implements the fix
    reg.register_provider(MockProvider(
        name="codex_coder",
        response_text="def login(): return True",
    ))

    # Reviewer 1 produces finding
    reg.register_provider(MockProvider(
        name="claude_reviewer",
        response_text=(
            "SEVERITY: high\n"
            "FILE: src/auth.py\n"
            "LINE: 1\n"
            "FINDING: Missing input validation on credentials\n"
            "EVIDENCE: def login() accepts no arguments\n"
            "RECOMMENDATION: Add username and password validation\n"
            "CONFIDENCE: 0.95\n"
        ),
    ))

    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    result = await router.execute_review_workflow(
        task_id="t-review-1",
        session_id="s-review-1",
        prompt="Implement secure login function",
        coder_provider="codex_coder",
        reviewer_providers=["claude_reviewer"],
    )

    assert result["task_id"] == "t-review-1"
    assert "def login()" in result["coder_output"]
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["severity"] == "high"
    assert finding["file"] == "src/auth.py"
    assert finding["confidence"] == 0.95


@pytest.mark.asyncio
async def test_implementation_consensus_workflow(tmp_path):
    reg = ProviderRegistry()

    reg.register_provider(MockProvider(
        name="provider_a",
        response_text="Implementation A: Fast in-memory cache",
    ))
    reg.register_provider(MockProvider(
        name="provider_b",
        response_text="Implementation B: Redis-backed distributed cache",
    ))

    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    res = await router.execute_consensus_workflow(
        task_id="t-consensus-1",
        session_id="s-consensus-1",
        prompt="Implement caching solution",
        candidate_providers=["provider_a", "provider_b"],
    )

    assert res["task_id"] == "t-consensus-1"
    assert res["winning_provider"] in ("provider_a", "provider_b")
    assert len(res["evaluations"]) == 2
