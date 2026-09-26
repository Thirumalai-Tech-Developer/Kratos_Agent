"""Tests for automatic failover and circuit breaker protection during task execution."""

import pytest
from kratos_agent.providers.mock import MockProvider, FailingProvider
from kratos_agent.providers.registry import ProviderRegistry
from kratos_agent.providers.router import ProviderRouter


@pytest.mark.asyncio
async def test_automatic_failover_to_healthy_provider(tmp_path):
    reg = ProviderRegistry()
    # Register failing provider and healthy fallback
    reg.register_provider(FailingProvider(name="primary_failing", fail_count=10))
    reg.register_provider(MockProvider(name="secondary_healthy", response_text="Fallback success!"))
    reg.set_fallback_chain(["primary_failing", "secondary_healthy"])

    router = ProviderRouter(registry=reg, workspace_root=tmp_path)

    run = await router.execute_task(
        task_id="task-failover-1",
        session_id="session-failover-1",
        prompt="Execute task",
        requested_provider="primary_failing",
    )

    # Must succeed via the fallback provider
    assert run.status == "completed"
    assert "Fallback success!" in run.output
    assert run.provider == "secondary_healthy"

    # Primary circuit breaker should have recorded failure
    cb = reg.circuit_breaker("primary_failing")
    assert cb.failure_count > 0
