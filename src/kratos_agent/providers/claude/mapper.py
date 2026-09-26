"""Claude event and error normalization mapper (§15)."""
from __future__ import annotations

from typing import Any

from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    redact_secrets,
)


def map_claude_event(raw_event: Any, task_id: str, session_id: str) -> AgentEvent | None:
    """Translates Claude Agent SDK or Anthropic streaming events to canonical AgentEvent."""
    if isinstance(raw_event, dict):
        event_type = raw_event.get("type", "")
        if event_type == "content_block_delta":
            delta = raw_event.get("delta", {}).get("text", "")
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="claude",
                event_type=CanonicalEventType.TOKEN_DELTA,
                payload={"delta": delta},
            )
        if event_type == "tool_use":
            tool_name = raw_event.get("name", "tool")
            args = raw_event.get("input", {})
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="claude",
                event_type=CanonicalEventType.TOOL_CALL_STARTED,
                payload={"tool": tool_name, "args": args},
                voice_narratable=True,
                voice_text=f"Claude executing tool {tool_name}",
            )

    return None


def map_claude_error(exc: Exception) -> dict[str, Any]:
    """Extracts structured diagnostic error metadata from Claude exceptions."""
    err_type = type(exc).__name__
    msg = redact_secrets(str(exc))
    return {
        "provider": "claude",
        "error_type": err_type,
        "message": msg,
        "is_rate_limit": "rate_limit" in err_type.lower() or "429" in msg,
        "is_auth_error": "auth" in err_type.lower() or "401" in msg,
    }
