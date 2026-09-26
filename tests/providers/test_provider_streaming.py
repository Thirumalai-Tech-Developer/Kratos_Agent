"""Tests for true token and event streaming across provider adapters."""

import pytest
from kratos_agent.providers.events import CanonicalEventType
from kratos_agent.providers.mock import StreamingProvider


@pytest.mark.asyncio
async def test_provider_stream_events_and_deltas():
    provider = StreamingProvider(
        name="test_streamer",
        stream_chunks=["Hello", " ", "world", " from", " streaming", " backend!"],
    )

    events = []
    text_deltas = []

    async for ev in provider.stream(
        task_id="task-stream-1",
        session_id="session-stream-1",
        prompt="Stream this text",
    ):
        events.append(ev)
        if ev.event_type == CanonicalEventType.ASSISTANT_DELTA:
            text_deltas.append(ev.payload.get("delta", ""))

    assert len(events) >= 8  # task started + 6 chunks + task completed
    assert "".join(text_deltas) == "Hello world from streaming backend!"
    assert events[0].event_type == CanonicalEventType.TASK_STARTED
    assert events[-1].event_type == CanonicalEventType.TASK_COMPLETED
