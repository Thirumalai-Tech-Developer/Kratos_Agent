"""Tests for task interruption across provider execution."""

import pytest
from kratos_agent.providers.events import CanonicalEventType
from kratos_agent.providers.mock import InterruptibleProvider, MockProvider
from kratos_agent.providers.base import ProviderCapabilityError


@pytest.mark.asyncio
async def test_interrupt_supported_provider():
    provider = InterruptibleProvider(name="mock_interruptible")

    # Trigger interrupt immediately
    await provider.interrupt("task-int-1")
    assert "task-int-1" in provider.interrupted_tasks

    events = []
    async for ev in provider.stream("task-int-1", "session-int-1", "Do something long"):
        events.append(ev)

    # Interrupted event must be yielded
    interrupted_events = [e for e in events if e.event_type == CanonicalEventType.TASK_INTERRUPTED]
    assert len(interrupted_events) == 1
    assert "interrupted" in interrupted_events[0].voice_text.lower()


@pytest.mark.asyncio
async def test_interrupt_unsupported_provider_raises():
    provider = MockProvider(name="mock_non_interruptible")
    # MockProvider does not support interrupt by default
    with pytest.raises(ProviderCapabilityError):
        await provider.interrupt("task-int-2")
