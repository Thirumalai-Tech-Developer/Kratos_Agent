"""Context bridge connecting Kratos Memory Engine and Workspace state to providers.

Enforces §13 & §14:
- Kratos Memory -> Context Builder -> Provider-specific context.
- Content-aware compression: never leak megabytes of raw history unnecessarily.
- Secret redaction at the provider boundary.
"""
from __future__ import annotations

import logging
from typing import Any

from kratos_agent.memory.manager import MemoryManager
from kratos_agent.providers.events import redact_secrets

logger = logging.getLogger(__name__)


class ProviderContextBridge:
    """Extracts, formats, and compacts Kratos memory and state into provider prompts."""

    def __init__(
        self,
        memory_manager: MemoryManager | None = None,
        max_context_length: int = 16_000,
    ) -> None:
        self.memory = memory_manager
        self.max_context_length = max_context_length

    def build_system_context(
        self,
        provider_name: str,
        user_instructions: str = "",
        workspace_summary: str = "",
        memory_snippets: list[str] | None = None,
        visual_summary: str = "",
    ) -> str:
        """Constructs a compact, layered system directive for external runtimes."""
        # 1. Essential directives that must never be dropped
        core_parts = [
            f"KRATOS SPECIALIST DIRECTIVE (Runtime: {provider_name})",
            "KRATOS IS THE COORDINATOR. Execute your assigned capability with precision.",
            "All actions will be verified by Kratos before task completion.",
        ]
        if user_instructions:
            core_parts.append(f"TASK DIRECTIVE:\n{user_instructions}")
        if workspace_summary:
            core_parts.append(f"WORKSPACE STATUS:\n{workspace_summary}")
        if visual_summary:
            core_parts.append(f"VISUAL CONTEXT:\n{visual_summary}")

        core_text = "\n\n".join(core_parts)

        # 2. Auxiliary memory: allocated remaining budget
        remaining_budget = max(200, self.max_context_length - len(core_text) - 100)
        memory_part = ""
        if memory_snippets:
            mem_lines = []
            cur_len = 0
            for s in memory_snippets:
                if cur_len + len(s) + 5 > remaining_budget:
                    break
                mem_lines.append(f"- {s}")
                cur_len += len(s) + 5
            if mem_lines:
                memory_part = "RELEVANT MEMORY:\n" + "\n".join(mem_lines)

        full_parts = [core_text]
        if memory_part:
            full_parts.append(memory_part)

        full_text = "\n\n".join(full_parts)
        redacted = redact_secrets(full_text)

        if len(redacted) > self.max_context_length:
            redacted = redacted[: self.max_context_length - 50] + "\n...[truncated for context budget]"

        return redacted

    def assemble_context(
        self,
        task_id: str,
        session_id: str,
        instruction: str,
        workspace_path: str = "",
        visual_context: dict[str, Any] | None = None,
        max_context_tokens: int = 16_000,
    ) -> dict[str, Any]:
        """Constructs a clean, layered context payload for external agent backends."""
        system_rules = (
            "You are an expert specialist working under the Kratos Autonomous Platform.\n"
            "KRATOS IS THE COORDINATOR. Execute your assigned task with precision.\n"
            "When performing actions, invoke tools directly. Do not output conversational filler.\n"
            "All output will be authoritatively verified by Kratos before task completion."
        )

        recalled_memories = []
        if self.memory:
            try:
                records = self.memory.recall(text=instruction, limit=3, min_confidence=0.3)
                for r in records:
                    recalled_memories.append(f"- {r.content}")
            except Exception as exc:
                logger.debug("Memory recall skipped: %s", exc)

        memory_section = ""
        if recalled_memories:
            memory_section = "RELEVANT PROJECT & SEMANTIC MEMORY:\n" + "\n".join(recalled_memories)

        visual_section = ""
        if visual_context:
            source = visual_context.get("source", "screen")
            summary = visual_context.get("summary", "")
            visual_section = f"VISUAL CONTEXT [{source}]:\n{summary}"

        # Clean and redact
        instruction_clean = redact_secrets(instruction)

        combined_system = "\n\n".join(part for part in [system_rules, memory_section, visual_section] if part)

        return {
            "task_id": task_id,
            "session_id": session_id,
            "system_instruction": combined_system,
            "user_instruction": instruction_clean,
            "workspace_path": workspace_path,
            "visual_context": visual_context,
        }
