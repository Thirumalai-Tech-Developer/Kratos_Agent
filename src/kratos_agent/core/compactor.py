import re
from typing import List, Dict, Any, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(highlight=False)

COMPACTION_SYSTEM_PROMPT = """You are an expert AI context compactor. 
Summarize the previous conversation turns into a dense, high-fidelity context memory checkpoint.
Preserve all:
1. User goals and requirements
2. Files created, modified, or executed
3. Important decisions, errors encountered, and solutions
4. Current state of the workspace
Format as a clear, concise bulleted summary."""

class ConversationCompactor:
    """Manages multi-turn conversation compression, token optimization, and history pruning."""

    def __init__(self, max_turns: int = 8, keep_recent_turns: int = 4):
        self.max_turns = max_turns
        self.keep_recent_turns = keep_recent_turns

    def estimate_tokens(self, text: str) -> int:
        """Rough estimation: ~4 chars per token."""
        return max(1, len(str(text)) // 4)

    def prune_tool_output(self, content: str, max_chars: int = 300) -> str:
        """Trims verbose STDOUT / STDERR while preserving exit codes and key status lines."""
        content_str = str(content).strip()
        if len(content_str) <= max_chars:
            return content_str
        
        # Keep first 3 lines and last 2 lines
        lines = content_str.splitlines()
        if len(lines) > 6:
            head = "\n".join(lines[:3])
            tail = "\n".join(lines[-2:])
            return f"{head}\n... [trimmed {len(lines) - 5} lines] ...\n{tail}"
        return content_str[:max_chars] + "... [trimmed]"

    def compress_heuristic(self, older_messages: List[Dict[str, str]]) -> str:
        """Fast offline compression when LLM invocation is skipped."""
        summary_lines = ["[COMPACTED CONVERSATION CHECKPOINT]"]
        for m in older_messages:
            role = m.get("role", "user").capitalize()
            content = m.get("content", "").strip()
            # Extract first sentence or intent
            first_line = content.splitlines()[0] if content else ""
            if len(first_line) > 120:
                first_line = first_line[:120] + "..."
            summary_lines.append(f"- {role}: {first_line}")
        return "\n".join(summary_lines)

    def compress_messages(
        self, 
        messages: List[Dict[str, str]], 
        brain: Optional[Any] = None,
        force: bool = False
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """
        Compresses message history if message count exceeds threshold or force is True.
        Returns: (compressed_messages, stats_dict)
        """
        initial_chars = sum(len(m.get("content", "")) for m in messages)
        initial_tokens = self.estimate_tokens(" ".join(m.get("content", "") for m in messages))
        initial_count = len(messages)

        if not force and len(messages) < self.max_turns:
            return messages, {
                "compressed": False,
                "initial_count": initial_count,
                "final_count": initial_count,
                "initial_tokens": initial_tokens,
                "final_tokens": initial_tokens,
                "reduction_percent": 0.0
            }

        # Divide into older turns to compress and recent active turns to keep
        split_idx = max(0, len(messages) - self.keep_recent_turns)
        older_messages = messages[:split_idx]
        recent_messages = messages[split_idx:]

        if not older_messages:
            return messages, {
                "compressed": False,
                "initial_count": initial_count,
                "final_count": initial_count,
                "initial_tokens": initial_tokens,
                "final_tokens": initial_tokens,
                "reduction_percent": 0.0
            }

        summary_text = ""
        # 1. Try LLM compression if brain is provided
        if brain:
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                history_str = "\n\n".join(
                    f"{m.get('role', 'user').upper()}: {self.prune_tool_output(m.get('content', ''))}"
                    for m in older_messages
                )
                prompt = f"{COMPACTION_SYSTEM_PROMPT}\n\nCONVERSATION TO SUMMARIZE:\n{history_str}"
                res = brain.invoke([HumanMessage(content=prompt)])
                summary_text = getattr(res, "content", str(res)).strip()
            except Exception:
                summary_text = self.compress_heuristic(older_messages)
        else:
            summary_text = self.compress_heuristic(older_messages)

        # Build new compacted message list
        compacted_summary_msg = {
            "role": "user",
            "content": f"[CONVERSATION CONTEXT CHECKPOINT]\n{summary_text}\n\n(Previous conversation has been compressed. Continue from here.)"
        }
        compacted_ack_msg = {
            "role": "assistant",
            "content": "Context checkpoint acknowledged. Ready for your next command."
        }

        new_messages = [compacted_summary_msg, compacted_ack_msg] + recent_messages

        final_chars = sum(len(m.get("content", "")) for m in new_messages)
        final_tokens = self.estimate_tokens(" ".join(m.get("content", "") for m in new_messages))
        reduction = max(0.0, ((initial_tokens - final_tokens) / initial_tokens) * 100) if initial_tokens > 0 else 0.0

        stats = {
            "compressed": True,
            "initial_count": initial_count,
            "final_count": len(new_messages),
            "initial_tokens": initial_tokens,
            "final_tokens": final_tokens,
            "reduction_percent": round(reduction, 1)
        }

        return new_messages, stats

# Global compactor instance
compactor = ConversationCompactor()
