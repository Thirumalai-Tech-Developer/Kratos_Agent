"""Kimi event and error normalization mapper (§17)."""
from __future__ import annotations

from typing import Any

from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    redact_secrets,
)


def map_kimi_event(raw_event: Any, task_id: str, session_id: str) -> AgentEvent | None:
    """Translates Kimi / Moonshot agent events into canonical AgentEvents."""
    if isinstance(raw_event, dict):
        event_type = raw_event.get("event") or raw_event.get("type")
        if event_type in ("chunk", "token", "content"):
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="kimi",
                event_type=CanonicalEventType.TOKEN_DELTA,
                payload={"delta": raw_event.get("text", "")},
            )
        if event_type == "tool_call":
            tool_name = raw_event.get("name", "tool")
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="kimi",
                event_type=CanonicalEventType.TOOL_CALL_STARTED,
                payload={"tool": tool_name, "args": raw_event.get("arguments", {})},
                voice_narratable=True,
                voice_text=f"Kimi invoking tool {tool_name}",
            )
    return None


def map_kimi_error(exc: Exception) -> dict[str, Any]:
    """Extracts structured diagnostic error metadata from Kimi exceptions."""
    err_type = type(exc).__name__
    msg = redact_secrets(str(exc))
    return {
        "provider": "kimi",
        "error_type": err_type,
        "message": msg,
        "is_rate_limit": "rate_limit" in err_type.lower() or "429" in msg,
        "is_auth_error": "auth" in err_type.lower() or "401" in msg,
    }
