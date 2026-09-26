"""Tests for voice narration sanitization, throttling, and honesty."""

import pytest
from kratos_agent.live.narration import NarrationManager, sanitize_speech_text
from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent


def test_sanitize_speech_text():
    raw = "The API key is sk-123456789012345678901234567890 and Bearer auth_token_secret_123456"
    sanitized = sanitize_speech_text(raw)
    assert "sk-" not in sanitized
    assert "auth_token" not in sanitized
    assert "[REDACTED]" in sanitized


def test_narration_manager_spoken_events():
    spoken = []

    def fake_speak(text: str):
        spoken.append(text)

    nm = NarrationManager(send_speech_fn=fake_speak, min_interval_seconds=0.0)
    nm.is_active = True

    # 1. Starting task
    nm.on_event(RuntimeEvent(
        kind=EventKind.TASK_STARTED,
        payload={"title": "Fix memory leak in buffer pool"},
        turn_id="t-1",
    ))
    assert len(spoken) == 1
    assert "Starting task: Fix memory leak" in spoken[0]

    # 2. Voice text from AgentEvent
    nm.on_event(RuntimeEvent(
        kind=EventKind.TURN_STARTED,
        payload={"voice_text": "Running test suite on authentication.", "voice_priority": 85},
        turn_id="t-2",
    ))
    assert len(spoken) == 2
    assert "Running test suite" in spoken[1]
