"""Token-budgeted context assembly and deterministic tool-result pruning.

Integrates optional Headroom compression (headroomlabs-ai/headroom) to
reduce token usage by 20-60% on tool outputs, logs, and JSON before
they reach the LLM. Headroom is optional — if not installed, the
existing head/tail truncation logic applies unchanged.
"""
from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from datetime import datetime, timezone
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
    max_input_tokens: int = 256_000
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
        self.reset_tracking()

    def reset_tracking(self) -> None:
        self.overhead_tokens = 0
        self.last_input_tokens: int | None = None
        self.provider_input_tokens: int | None = None
        self.compaction_count = 0
        self.last_compaction: dict[str, Any] | None = None

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def history_tokens(self, messages: list[ChatMessage]) -> int:
        # Include native tool arguments and message framing, not just visible text.
        return sum(self.estimate_tokens(json.dumps({
            "role": message.role, "content": message.content,
            "tool_calls": message.metadata.get("tool_calls"),
            "tool_call_id": message.tool_call_id, "name": message.name,
        }, ensure_ascii=False, default=str)) for message in messages)

    def snapshot(self, history: list[ChatMessage] | None = None) -> dict[str, Any]:
        capacity = max(1, self.budget.max_input_tokens - self.budget.reserve_output_tokens)
        estimated = self.overhead_tokens + self.history_tokens(history) if history is not None else (self.last_input_tokens or 0)
        measured = history is None and self.provider_input_tokens is not None
        used = self.provider_input_tokens if measured else estimated
        return {
            "used_tokens": used, "estimated_tokens": estimated,
            "measurement": "provider" if measured else "estimated",
            "provider_input_tokens": self.provider_input_tokens,
            "overhead_known": self.last_input_tokens is not None,
            "scope": "working_context" if history is not None else "last_request",
            "context_limit": self.budget.max_input_tokens,
            "input_limit": capacity, "reserved_output_tokens": self.budget.reserve_output_tokens,
            "percent_used": round(100 * used / capacity, 1),
            "auto_compact_at_tokens": int(capacity * 0.9),
            "over_limit": used > capacity,
            "compaction_count": self.compaction_count, "last_compaction": self.last_compaction,
        }

    def record_usage(self, usage: dict[str, Any] | None) -> None:
        if isinstance(usage, dict):
            value = usage.get("prompt_tokens", usage.get("input_tokens"))
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self.provider_input_tokens = value

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

    def compact_history(self, messages: list[ChatMessage], *, force: bool = False,
                        overhead_tokens: int = 0) -> tuple[list[ChatMessage], dict[str, Any] | None]:
        capacity = max(1, self.budget.max_input_tokens - self.budget.reserve_output_tokens)
        limit = max(1, capacity - overhead_tokens)
        total = self.history_tokens(messages)
        if (not force and total + overhead_tokens < int(capacity * 0.9)) or len(messages) <= 1:
            return messages, None

        # Assistant tool calls and their results form one indivisible group.
        # Never leave an orphan tool result in a provider request.
        groups: list[list[ChatMessage]] = []
        for message in messages:
            if message.role == "tool" and groups:
                groups[-1].append(message)
            else:
                groups.append([message])
        internal_user_prefixes = (
            "[System Directive",
            "[RUNTIME VERIFICATION FAILED",
            "[COMPACTION CHECKPOINT]",
        )
        root = next((i for i in range(len(groups) - 1, -1, -1)
                     if groups[i][0].role == "user" and not groups[i][0].content.startswith(internal_user_prefixes)), None)
        keep = {len(groups) - 1}
        if root is not None:
            keep.add(root)
        used = sum(self.history_tokens(groups[i]) for i in keep)
        target = min(total // 2, int(limit * 0.6))
        for i in range(len(groups) - 1, -1, -1):
            if i in keep:
                continue
            cost = self.history_tokens(groups[i])
            if used + cost > target:
                break
            keep.add(i)
            used += cost
        omitted = [message for i, group in enumerate(groups) if i not in keep for message in group]
        if not omitted:
            return messages, None
        # Bound the checkpoint itself; older large transcripts must actually shrink.
        facts = [f"- {m.role}: {m.content[:220].replace(chr(10), ' ')}" for m in omitted if m.content.strip()]
        summary_limit = min(2400, max(0, (total - used - 50) * 2))
        if summary_limit < 80:
            return messages, None
        checkpoint = ChatMessage("user", "[COMPACTION CHECKPOINT]\nOlder steps summarized; full history remains in session records.\n"
                                 + "\n".join(facts)[-summary_limit:], metadata={"compacted": True})
        result = [checkpoint] + [m for i, group in enumerate(groups) if i in keep for m in group]
        after = self.history_tokens(result)
        if after >= total:
            return messages, None
        detail = {"before_tokens": total + overhead_tokens, "after_tokens": after + overhead_tokens,
                  "saved_tokens": total - after, "omitted_messages": len(omitted),
                  "reason": "manual" if force else "automatic", "at": datetime.now(timezone.utc).isoformat()}
        self.compaction_count += 1
        self.last_compaction = detail
        self.provider_input_tokens = None
        return result, detail

    def assemble(
        self,
        instruction_sections: list[dict[str, str]],
        history: list[ChatMessage],
        tools: list[dict[str, Any]],
        workspace: dict[str, Any],
        run_state: Any | None = None,
    ) -> dict[str, Any]:
        self._headroom_stats.clear()
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

        # Native schemas consume input tokens too. Workspace metadata is local
        # adapter state and is not sent as a separate model message.
        self.overhead_tokens = self.estimate_tokens(system) + (
            self.estimate_tokens(json.dumps(tools, ensure_ascii=False, default=str)) + 128 if tools else 0)
        history, compaction = self.compact_history(history, overhead_tokens=self.overhead_tokens)
        token_estimate = self.overhead_tokens + self.history_tokens(history)
        self.last_input_tokens = token_estimate
        self.provider_input_tokens = None
        request = {
            "instructions": instruction_sections,
            "system": system,
            "messages": [message.to_dict() for message in history],
            "tools": tools,
            "workspace": workspace,
            "token_estimate": token_estimate,
            "context_usage": self.snapshot(),
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
