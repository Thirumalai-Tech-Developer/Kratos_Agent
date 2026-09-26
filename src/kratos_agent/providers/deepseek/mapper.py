"""DeepSeek Harness event and error normalization mapper (§18)."""
from __future__ import annotations

import re
from typing import Any

from kratos_agent.providers.events import (
    AgentEvent,
    CanonicalEventType,
    EventSeverity,
    redact_secrets,
)


def extract_reasoning_and_content(raw_text: str) -> tuple[str, str]:
    """Splits <think>...</think> reasoning blocks from user-visible response."""
    if not raw_text:
        return "", ""
    think_pattern = re.compile(r"<think>(.*?)(?:</think>|$)", re.DOTALL | re.IGNORECASE)
    matches = think_pattern.findall(raw_text)
    reasoning = "\n\n".join(m.strip() for m in matches if m.strip())
    cleaned_content = think_pattern.sub("", raw_text).strip()
    return reasoning, cleaned_content


def map_deepseek_event(raw_event: Any, task_id: str, session_id: str) -> AgentEvent | None:
    """Translates DeepSeek Harness runtime / JSON-RPC events into canonical AgentEvents."""
    if isinstance(raw_event, dict):
        event_type = raw_event.get("method") or raw_event.get("type", "")
        params = raw_event.get("params") or raw_event.get("data", {})

        if "reasoning" in event_type or "think" in event_type:
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="deepseek",
                event_type=CanonicalEventType.REASONING_DELTA,
                payload={"reasoning": params.get("text", "")},
            )
        if "delta" in event_type or "token" in event_type:
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="deepseek",
                event_type=CanonicalEventType.TOKEN_DELTA,
                payload={"delta": params.get("delta", "")},
            )
        if "tool" in event_type:
            tool_name = params.get("name", "tool")
            return AgentEvent(
                task_id=task_id,
                session_id=session_id,
                provider="deepseek",
                event_type=CanonicalEventType.TOOL_CALL_STARTED,
                payload={"tool": tool_name, "args": params.get("arguments", {})},
                voice_narratable=True,
                voice_text=f"DeepSeek executing {tool_name}",
            )

    return None


def map_deepseek_error(exc: Exception) -> dict[str, Any]:
    """Extracts structured diagnostic error metadata from DeepSeek exceptions."""
    err_type = type(exc).__name__
    msg = redact_secrets(str(exc))
    return {
        "provider": "deepseek",
        "error_type": err_type,
        "message": msg,
        "is_rate_limit": "rate_limit" in err_type.lower() or "429" in msg,
        "is_auth_error": "auth" in err_type.lower() or "401" in msg,
    }
