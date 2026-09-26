"""Codex event and error normalization mapper (§16)."""
from __future__ import annotations

from typing import Any

from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    redact_secrets,
)


def map_codex_event(raw_event: Any, task_id: str, session_id: str) -> AgentEvent | None:
    """Translates Codex / OpenAI turn events into canonical AgentEvents."""
    if isinstance(raw_event, dict):
        event_type = raw_event.get("event", "")
        data = raw_event.get("data", {})
        if event_type == "thread.message.delta":
            delta_content = data.get("delta", {}).get("content", [])
            for c in delta_content:
                if c.get("type") == "text":
                    return AgentEvent(
                        task_id=task_id,
                        session_id=session_id,
                        provider="codex",
                        event_type=CanonicalEventType.TOKEN_DELTA,
                        payload={"delta": c.get("text", {}).get("value", "")},
                    )
        elif event_type == "thread.run.step.delta":
            step_details = data.get("delta", {}).get("step_details", {})
            if step_details.get("type") == "tool_calls":
                for tc in step_details.get("tool_calls", []):
                    return AgentEvent(
                        task_id=task_id,
                        session_id=session_id,
                        provider="codex",
                        event_type=CanonicalEventType.TOOL_CALL_STARTED,
                        payload={"tool": tc.get("function", {}).get("name", "tool")},
                        voice_narratable=True,
                        voice_text=f"Codex invoking tool {tc.get('function', {}).get('name', 'tool')}",
                    )

    return None


def map_codex_error(exc: Exception) -> dict[str, Any]:
    """Extracts structured diagnostic error metadata from Codex exceptions."""
    err_type = type(exc).__name__
    msg = redact_secrets(str(exc))
    return {
        "provider": "codex",
        "error_type": err_type,
        "message": msg,
        "is_rate_limit": "rate_limit" in err_type.lower() or "429" in msg,
        "is_auth_error": "auth" in err_type.lower() or "401" in msg,
    }
