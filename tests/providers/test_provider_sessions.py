"""Tests for provider session correlation, reuse, and lifecycle."""

import pytest
from kratos_agent.providers.base import AgentSession
from kratos_agent.providers.mock import MockProvider


@pytest.mark.asyncio
async def test_session_mapping_and_reuse():
    provider = MockProvider(name="mock_session_provider")

    # Start first session
    session1 = await provider.start_session("t-1", "kratos-user-session-123")
    assert session1.session_id == "kratos-user-session-123"
    assert session1.provider == "mock_session_provider"

    # Start again with same session_id -> must reuse existing session
    session2 = await provider.start_session("t-2", "kratos-user-session-123")
    assert session2 is session1
    assert session2.provider_session_id == session1.provider_session_id

    # Close session
    await provider.close("kratos-user-session-123")
    assert "kratos-user-session-123" not in provider._sessions
