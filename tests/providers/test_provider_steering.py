"""Tests for mid-turn steering across provider execution."""

import pytest
from kratos_agent.providers.mock import SteerableProvider, MockProvider
from kratos_agent.providers.base import ProviderCapabilityError


@pytest.mark.asyncio
async def test_steering_supported_provider():
    provider = SteerableProvider(name="mock_steerable")

    await provider.steer("task-steer-1", "Change implementation from dict to list")
    assert "task-steer-1" in provider.steered_tasks
    assert provider.steered_tasks["task-steer-1"] == "Change implementation from dict to list"


@pytest.mark.asyncio
async def test_steering_unsupported_provider_raises():
    provider = MockProvider(name="mock_non_steerable")
    with pytest.raises(ProviderCapabilityError):
        await provider.steer("task-steer-2", "Do something else")
