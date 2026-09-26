"""Event and error mapping for Antigravity Python SDK."""

from __future__ import annotations

import logging
from typing import Any

from kratos_agent.providers.base import (
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderConfigurationError,
    ProviderError,
    ProviderExecutionError,
    ProviderTimeout,
    ProviderUnavailable,
)
from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    redact_secrets,
)

logger = logging.getLogger(__name__)


def map_antigravity_error(error: Exception, provider: str = "antigravity") -> ProviderError:
    """Map Antigravity SDK exceptions into canonical Kratos ProviderError hierarchy."""
    if isinstance(error, ProviderError):
        return error

    err_str = str(error).lower()
    err_type = type(error).__name__.lower()

    if "auth" in err_str or "unauthorized" in err_str or "key" in err_str:
        return ProviderAuthenticationError(
            provider=provider,
            message=redact_secrets(f"Antigravity authentication error: {error}"),
            original_exception=error,
        )
    if "not installed" in err_str or "unavailable" in err_str or "binary" in err_str:
        return ProviderUnavailable(
            provider=provider,
            message=redact_secrets(f"Antigravity runtime or binary unavailable: {error}"),
            original_exception=error,
        )
    if "timeout" in err_str or "deadline" in err_str:
        return ProviderTimeout(
            provider=provider,
            message=redact_secrets(f"Antigravity request timed out: {error}"),
            original_exception=error,
        )
    if "not supported" in err_str or "unsupported" in err_str or "capability" in err_str:
        return ProviderCapabilityError(
            provider=provider,
            message=redact_secrets(f"Antigravity unsupported capability: {error}"),
            original_exception=error,
        )
    if "config" in err_str or "missing parameter" in err_str:
        return ProviderConfigurationError(
            provider=provider,
            message=redact_secrets(f"Antigravity configuration error: {error}"),
            original_exception=error,
        )

    return ProviderExecutionError(
        provider=provider,
        message=redact_secrets(f"Antigravity execution failed: {error}"),
        original_exception=error,
    )


def map_antigravity_token_event(
    task_id: str,
    session_id: str,
    token: str,
) -> AgentEvent:
    """Map a streamed token into an AgentEvent."""
    return AgentEvent(
        task_id=task_id,
        session_id=session_id,
        provider="antigravity",
        event_type=CanonicalEventType.ASSISTANT_DELTA,
        payload={"delta": redact_secrets(token)},
        narratable=False,
    )


def map_antigravity_thought_event(
    task_id: str,
    session_id: str,
    thought: str,
) -> AgentEvent:
    """Map an internal reasoning thought into an AgentEvent (safe diagnostics, not narrated)."""
    return AgentEvent(
        task_id=task_id,
        session_id=session_id,
        provider="antigravity",
        event_type=CanonicalEventType.ASSISTANT_THOUGHT,
        payload={"thought": redact_secrets(thought)},
        narratable=False,
    )


def map_antigravity_tool_call(
    task_id: str,
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> AgentEvent:
    """Map a tool call invocation into an AgentEvent."""
    return AgentEvent(
        task_id=task_id,
        session_id=session_id,
        provider="antigravity",
        event_type=CanonicalEventType.TOOL_CALL_STARTED,
        payload={
            "tool_name": tool_name,
            "arguments": args,
        },
        voice_text=f"Executing tool {tool_name}",
        voice_priority=50,
        narratable=True,
    )
