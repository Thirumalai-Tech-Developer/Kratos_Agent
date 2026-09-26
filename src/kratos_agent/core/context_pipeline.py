"""Token-budgeted context assembly and deterministic tool-result pruning.

Integrates optional Headroom compression (headroomlabs-ai/headroom) to
reduce token usage by 20-60% on tool outputs, logs, and JSON before
they reach the LLM. Headroom is optional — if not installed, the
existing head/tail truncation logic applies unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

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


def headroom_compress_text(text: str, content_type: str = "text") -> tuple[str, dict[str, Any]]:
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


CONTEXT_BUDGET: dict[str, int] = {
    "system": 2500,
    "memory": 1200,
    "state": 2000,
    "tools": 2500,
    "conversation": 4000,
}


@dataclass
class ContextBudget:
    max_input_tokens: int = 100_000
    reserve_output_tokens: int = 8_000
    max_tool_result_chars: int = 12_000
    system_tokens: int = 2500
    memory_tokens: int = 1200
    state_tokens: int = 2000
    tools_tokens: int = 2500
    conversation_tokens: int = 4000


class ContextBuilder:
    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()
        self._headroom_stats: list[dict[str, Any]] = []

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def prune_tool_result(self, text: str) -> tuple[str, bool]:
        # Step 1: Try Headroom compression first (if available)
        content_type = detect_content_type(text)
        compressed, hr_stats = headroom_compress_text(text, content_type=content_type)
        if hr_stats.get("compressed"):
            self._headroom_stats.append(hr_stats)
            text = compressed

        # Step 2: Apply existing head/tail truncation if still too long
        if len(text) <= self.budget.max_tool_result_chars:
            return text, hr_stats.get("compressed", False)
            
        limit = self.budget.max_tool_result_chars
        lines = text.splitlines()
        
        # If text is composed of very few lines but massive length (e.g. minified code, base64)
        if len(lines) <= 5:
            half = limit // 2
            omitted_chars = max(0, len(text) - limit)
            truncated_text = f"{text[:half]}\n… [{omitted_chars} characters omitted; full result retained in session trace] …\n{text[-half:]}"
            return truncated_text, True

        head, tail = lines[:40], lines[-40:]
        omitted = max(0, len(lines) - len(head) - len(tail))
        truncated_text = "\n".join(head + [f"… [{omitted} lines omitted; full result retained in session trace] …"] + tail)
        
        # Guard against head+tail still exceeding character limit
        if len(truncated_text) > limit:
            half = limit // 2
            omitted_chars = max(0, len(truncated_text) - limit)
            truncated_text = f"{truncated_text[:half]}\n… [{omitted_chars} characters omitted] …\n{truncated_text[-half:]}"
            
        return truncated_text, True

    def compact_history(self, messages: list[ChatMessage]) -> tuple[list[ChatMessage], dict[str, Any] | None]:
        limit = self.budget.max_input_tokens - self.budget.reserve_output_tokens
        total = sum(self.estimate_tokens(message.content) for message in messages)
        if total <= limit or len(messages) <= 1:
            return messages, None

        # Always preserve the root user request (messages[0]) so the agent never loses its original task.
        root_user: ChatMessage | None = None
        remaining_messages = list(messages)
        if messages and messages[0].role == "user":
            root_user = messages[0]
            remaining_messages = messages[1:]

        # Preserve the newest turns from remaining_messages up to budget
        kept: list[ChatMessage] = []
        used = self.estimate_tokens(root_user.content) if root_user else 0
        target_limit = limit // 2

        for message in reversed(remaining_messages):
            cost = self.estimate_tokens(message.content)
            if kept and used + cost > target_limit:
                break
            kept.append(message)
            used += cost

        omitted = list(reversed(remaining_messages[: len(remaining_messages) - len(kept)]))
        facts = []
        for message in omitted:
            prefix = message.content.replace("\n", " ").strip()[:500]
            if prefix:
                facts.append(f"- {message.role}: {prefix}")

        checkpoint_messages: list[ChatMessage] = []
        if facts:
            # Use role="user" so web proxies and OpenAI adapters do not discard system messages inside the message array
            checkpoint_messages.append(ChatMessage(
                role="user",
                content="[COMPACTION CHECKPOINT]\nOlder execution steps were compacted. Retain these findings and constraints:\n" + "\n".join(facts),
                metadata={"compacted": True},
            ))

        result = ([root_user] if root_user else []) + checkpoint_messages + list(reversed(kept))
        return result, {"before_tokens": total, "after_tokens": sum(self.estimate_tokens(m.content) for m in result), "omitted_messages": len(omitted)}

    def assemble(
        self,
        instruction_sections: list[dict[str, str]],
        history: list[ChatMessage],
        tools: list[dict[str, Any]],
        workspace: dict[str, Any],
        run_state: Any | None = None,
    ) -> dict[str, Any]:
        self._headroom_stats.clear()
        history, compaction = self.compact_history(history)
        if isinstance(instruction_sections, str):
            system = instruction_sections
        elif isinstance(instruction_sections, (list, tuple)):
            parts = []
            for sec in instruction_sections:
                if isinstance(sec, dict):
                    parts.append(str(sec.get("content", "")))
                else:
                    parts.append(str(sec))
            system = "\n\n".join(parts)
        else:
            system = str(instruction_sections or "")

        # Inject active task banner if run_state exists to guarantee task preservation
        if run_state and getattr(run_state, "user_request", ""):
            req_text = run_state.user_request
            phase = getattr(run_state, "phase", "executing").upper()
            banner_lines = [
                "\n\n=======================================================",
                "🚨 CURRENT ACTIVE TASK (IMMUTABLE OBJECTIVE):",
                f"User Request: {req_text}",
                f"Phase: {phase}",
            ]
            deliverables = getattr(run_state, "target_deliverables", [])
            if deliverables:
                banner_lines.append(f"Required Deliverable Files: {', '.join(deliverables)}")
            inspected = getattr(run_state, "inspected_files", [])
            if inspected:
                banner_lines.append(f"Recently Inspected Files: {', '.join(inspected[-8:])}")
            banner_lines.extend([
                "DIRECTIVE: Proceed with completing the user's specific request. "
                "Do NOT output conversational 'no task' messages. "
                "Execute the required tools to fulfill and verify all deliverables.",
                "=======================================================",
            ])
            system += "\n".join(banner_lines)

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

