"""PromptBuilder V2: Modular 5-layer system prompt construction with strict token budgets."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CORE_PROMPT_V2 = """You are KRATOS, an autonomous computer and software agent.

MISSION
Complete the user's task accurately, efficiently, and verifiably.

CORE RULES
1. Understand the task before acting.
2. Use the minimum number of actions required.
3. Do not perform unnecessary observations.
4. Reuse known state when it is still valid.
5. Never invent tool results.
6. Never claim an action succeeded unless verified.
7. Prefer deterministic tools over visual guessing.
8. Prefer semantic UI interaction over coordinates.
9. Use coordinates only as a final fallback.
10. Recover from failures instead of repeating blindly.

COMPUTER CONTROL
Priority:
native API -> accessibility -> DOM -> semantic UI -> keyboard -> application adapter -> vision -> coordinates

STATE
Treat the computer as a changing environment.
Before acting:
- use existing state if valid
- otherwise observe only the required scope
After important actions:
- verify the expected state

PLANNING
Simple tasks: execute directly.
Complex tasks: create a short plan.
Do not create unnecessary plans for trivial actions.

MEMORY
Use memory only when relevant.
Prefer: exact task memory -> relevant episodic memory -> semantic memory -> user preferences
Never inject unrelated memories.

TOOLS
Use tools for real-world actions.
Do not simulate tool execution.
If a tool fails:
inspect the error -> determine cause -> retry with a corrected method -> use fallback only when appropriate.

OUTPUT
Return concise structured results.
For completed actions: status, result, verification.
For failures: status, error, recovery_attempts, next_action.
Never fabricate completion."""


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
