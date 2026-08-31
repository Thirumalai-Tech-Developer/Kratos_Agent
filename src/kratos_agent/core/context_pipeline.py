"""Token-budgeted context assembly and deterministic tool-result pruning."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from .runtime_contracts import ChatMessage


@dataclass
class ContextBudget:
    max_input_tokens: int = 100_000
    reserve_output_tokens: int = 8_000
    max_tool_result_chars: int = 12_000


class ContextBuilder:
    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def prune_tool_result(self, text: str) -> Tuple[str, bool]:
        if len(text) <= self.budget.max_tool_result_chars:
            return text, False
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
        history, compaction = self.compact_history(history)
        system = "\n\n".join(section["content"] for section in instruction_sections)
        request = {
            "instructions": instruction_sections,
            "system": system,
            "messages": [message.to_dict() for message in history],
            "tools": tools,
            "workspace": workspace,
            "token_estimate": self.estimate_tokens(system + "\n".join(m.content for m in history)),
        }
        return {"request": request, "compaction": compaction, "history": history}
