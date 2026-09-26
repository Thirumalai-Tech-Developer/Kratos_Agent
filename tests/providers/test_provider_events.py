"""Tests for canonical AgentEvent, secret redaction, and event bus mapping."""

import pytest
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    publish_agent_event,
    redact_secrets,
)
from kratos_agent.core.event_bus import event_bus


def test_secret_redaction_patterns():
    text_with_keys = (
        "Found token sk-abcdef1234567890abcdef123456 and api_key='secret1234567890' "
        "and Authorization: Bearer my-secret-token-value-here"
    )
    redacted = redact_secrets(text_with_keys)
    assert "sk-" not in redacted
    assert "secret1234567890" not in redacted
    assert "[REDACTED]" in redacted


def test_agent_event_voice_fields():
    event = AgentEvent(
        task_id="t-1",
        session_id="s-1",
        provider="codex",
        event_type=CanonicalEventType.TOOL_CALL_STARTED,
        payload={"tool": "pytest"},
        voice_text="Running the test suite.",
        voice_priority=75,
        narratable=True,
    )
    assert event.narratable is True
    assert event.voice_text == "Running the test suite."
    assert event.voice_priority == 75


def test_publish_agent_event_to_kratos_bus():
    received = []

    def handler(ev):
        received.append(ev)

    event_bus.subscribe(handler)
    try:
        event = AgentEvent(
            task_id="t-99",
            session_id="s-99",
            provider="kratos_native",
            event_type=CanonicalEventType.TASK_STARTED,
            payload={"task": "inspect repo"},
            voice_text="Starting repository inspection.",
        )
        publish_agent_event(event)
        assert len(received) > 0
        latest = received[-1]
        assert latest.turn_id == "t-99"
        assert latest.payload.get("voice_text") == "Starting repository inspection."
    finally:
        event_bus.unsubscribe(handler)
