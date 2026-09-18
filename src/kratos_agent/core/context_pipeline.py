"""Token-budgeted context assembly and deterministic tool-result pruning.

Integrates optional Headroom compression (headroomlabs-ai/headroom) to
reduce token usage by 20-60% on tool outputs, logs, and JSON before
they reach the LLM. Headroom is optional — if not installed, the
existing head/tail truncation logic applies unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .runtime_contracts import ChatMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Headroom lazy import — optional dependency
# ---------------------------------------------------------------------------
_headroom_plugin = None


def _get_headroom():
    """Try to retrieve the HeadroomPlugin instance. Cached after first call."""
    global _headroom_plugin
    if _headroom_plugin is None:
        try:
            from kratos_agent.core.harness.plugins.headroom_plugin import (
                HeadroomPlugin,
                is_headroom_available,
            )
            if is_headroom_available():
                _headroom_plugin = HeadroomPlugin()
                _headroom_plugin.on_load(None)
                _headroom_plugin.on_enable()
            else:
                _headroom_plugin = False  # Sentinel: checked but unavailable
        except Exception:
            _headroom_plugin = False
    return _headroom_plugin if _headroom_plugin and _headroom_plugin is not False else None


def headroom_compress_text(text: str, content_type: str = "text") -> Tuple[str, Dict[str, Any]]:
    """Compress text through Headroom if available, otherwise pass through."""
    plugin = _get_headroom()
    if plugin and plugin.available:
        return plugin.compress_text(text, content_type=content_type)
    return text, {"compressed": False, "reason": "headroom_unavailable"}


def detect_content_type(text: str) -> str:
    """Simple heuristic to detect content type for Headroom stats."""
    stripped = text.strip()
    if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
        return "json"
    if any(kw in stripped[:200] for kw in ("ERROR", "WARN", "INFO", "DEBUG", "FATAL", "Traceback")):
        return "log"
    if any(kw in stripped[:200] for kw in ("def ", "class ", "import ", "function ", "const ", "var ")):
        return "code"
    return "text"


@dataclass
class ContextBudget:
    max_input_tokens: int = 100_000
    reserve_output_tokens: int = 8_000
    max_tool_result_chars: int = 12_000


class ContextBuilder:
    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()
        self._headroom_stats: List[Dict[str, Any]] = []

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def prune_tool_result(self, text: str) -> Tuple[str, bool]:
        # Step 1: Try Headroom compression first (if available)
        content_type = detect_content_type(text)
        compressed, hr_stats = headroom_compress_text(text, content_type=content_type)
        if hr_stats.get("compressed"):
            self._headroom_stats.append(hr_stats)
            text = compressed

        # Step 2: Apply existing head/tail truncation if still too long
        if len(text) <= self.budget.max_tool_result_chars:
            return text, hr_stats.get("compressed", False)
        lines = text.splitlines()
        head, tail = lines[:40], lines[-40:]
        omitted = max(0, len(lines) - len(head) - len(tail))
        return "\n".join(head + [f"… [{omitted} lines omitted; full result retained in session trace] …"] + tail), True

    def compact_history(self, messages: List[ChatMessage]) -> Tuple[List[ChatMessage], Dict[str, Any] | None]:
        limit = self.budget.max_input_tokens - self.budget.reserve_output_tokens
        total = sum(self.estimate_tokens(message.content) for message in messages)
        if total <= limit:
            return messages, None
        # Preserve the newest turns verbatim and create a transparent checkpoint.
        kept: List[ChatMessage] = []
        used = 0
        for message in reversed(messages):
            cost = self.estimate_tokens(message.content)
            if kept and used + cost > limit // 2:
                break
            kept.append(message)
            used += cost
        omitted = list(reversed(messages[: len(messages) - len(kept)]))
        facts = []
        for message in omitted:
            prefix = message.content.replace("\n", " ").strip()[:500]
            if prefix:
                facts.append(f"- {message.role}: {prefix}")
        checkpoint = ChatMessage(
            role="system",
            content="[COMPACTION CHECKPOINT]\nOlder turns were compacted. Preserve these decisions and requirements:\n" + "\n".join(facts),
            metadata={"compacted": True},
        )
        result = [checkpoint] + list(reversed(kept))
        return result, {"before_tokens": total, "after_tokens": sum(self.estimate_tokens(m.content) for m in result), "omitted_messages": len(omitted)}

    def assemble(
        self,
        instruction_sections: List[Dict[str, str]],
        history: List[ChatMessage],
        tools: List[Dict[str, Any]],
        workspace: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._headroom_stats.clear()
        history, compaction = self.compact_history(history)
        system = "\n\n".join(section["content"] for section in instruction_sections)
        token_estimate = self.estimate_tokens(system + "\n".join(m.content for m in history))
        request = {
            "instructions": instruction_sections,
            "system": system,
            "messages": [message.to_dict() for message in history],
            "tools": tools,
            "workspace": workspace,
            "token_estimate": token_estimate,
        }
        # Include Headroom stats if any compressions occurred
        if self._headroom_stats:
            total_saved = sum(s.get("tokens_saved", 0) for s in self._headroom_stats)
            request["headroom"] = {
                "compressions": len(self._headroom_stats),
                "total_tokens_saved": total_saved,
                "details": self._headroom_stats,
            }
        return {"request": request, "compaction": compaction, "history": history}

