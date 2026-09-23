"""PromptBuilder V2: Modular 5-layer system prompt construction with strict token budgets."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CORE_PROMPT_V2 = """You are Kratos, an autonomous computer-use and software agent.

Complete tasks directly and efficiently.

For simple tasks, execute directly without unnecessary planning.

Do not inspect source files unless the task requires code changes or repository analysis.

Do not check dependencies for tools that are not being used.

Choose the simplest available execution backend.

For browser tasks, prefer the existing browser session and Playwright. Never use Selenium or ChromeDriver.

For desktop tasks, prefer semantic accessibility APIs before vision or coordinates.

Use the minimum number of actions required.

Do not narrate internal operations.

Do not generate progress messages for every tool call.

User-facing progress must contain only meaningful milestones.

Never claim success before verification.

After an important action, verify the resulting state.

If an action fails, diagnose the failure and use an appropriate fallback.

Do not repeat the same failed action blindly.

Never assume the shell is Bash.

Detect the current operating-system shell before executing shell commands.

Prefer direct process APIs over shell command strings.

On Windows, generate PowerShell-compatible commands when PowerShell is active.

Never send raw shell XML, CLIXML, debug output, or internal logs to the user.

Return structured tool actions.

Return a concise final result.

Never expose hidden chain-of-thought.

The final response should clearly indicate:
- success
- failure
- or partial completion

Only state facts confirmed by actual tool execution."""


@dataclass
class PromptBuilder:
    """Constructs prompt layers adhering to strict token budgets without bloat."""
    core: str = CORE_PROMPT_V2
    task: Optional[str] = None
    memory: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    state: Optional[Dict[str, Any]] = None

    def build(self) -> str:
        layers: List[str] = [self.core]

        # 1. Task Context
        if self.task and self.task.strip():
            layers.append(f"## TASK CONTEXT\n{self.task.strip()}")

        # 2. Relevant Memory (compact bullet points only)
        if self.memory:
            cleaned_memories = [m.strip() for m in self.memory if m and m.strip()]
            if cleaned_memories:
                mem_text = "\n".join(f"- {m}" for m in cleaned_memories[:5])
                layers.append(f"## RELEVANT MEMORY\n{mem_text}")

        # 3. Available Tools
        if self.tools:
            tool_list = ", ".join(self.tools)
            layers.append(f"## AVAILABLE TOOLS\n{tool_list}")

        # 4. Current State
        if self.state:
            active_win = (self.state.get("active_window") or {}).get("title", "Unknown")
            browser_url = (self.state.get("browser_state") or {}).get("url")
            state_lines = [f"Active Window: {active_win}"]
            if browser_url:
                state_lines.append(f"Browser URL: {browser_url}")
            layers.append(f"## CURRENT STATE\n" + "\n".join(state_lines))

        return "\n\n".join(layers)
