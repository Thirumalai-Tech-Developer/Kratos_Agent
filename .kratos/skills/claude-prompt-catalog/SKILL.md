---
name: claude-prompt-catalog
description: Comprehensive index and query guide for 500+ Claude Code system prompts, sub-agents (Explore, Plan, Review, Simplify, Security), data formats, and tools.
tags: prompts, system-prompts, claude-code, subagents, tools, catalog
source_url: https://github.com/Piebald-AI/claude-code-system-prompts
---

# Claude Code System Prompt & Sub-Agent Catalog

This skill provides access to all 515+ system prompts, sub-agents, tool descriptions, and operational instructions from Claude Code.

## Catalog Breakdown
- **Sub-Agents (`agent-prompt-*`)**: Explore, Plan mode enhanced, Code Review (minimal, low, high, xhigh modes), Security Review, Simplify, Conversation Summarizer, Onboarding Guide, and General Purpose workers.
- **System Prompts (`system-prompt-*`)**: Outcome-first communication, software engineering focus, action safety, file editing discipline, no-unnecessary error wrappers/additions, PowerShell editions, and autonomous operation.
- **Tool Descriptions (`tool-description-*` & `tool-parameter-*`)**: Bash/Terminal, Read, Write, Edit, Glob, Grep, TodoWrite, AskUserQuestion, and Background monitor.
- **Data & Protocol Schemas (`data-*`)**: Managed agents API, SDK protocols, prompt caching optimization, HTTP error references, and data visualization palettes.
- **System Reminders (`system-reminder-*`)**: Plan mode state, trust boundaries, memory constraints, and async agent lifecycles.

## Accessing Prompts in Kratos Agent
1. **CLI Commands**:
   - `/prompts <search_query>`: Search and preview prompts directly in the terminal.
   - `/review`: Run the Claude Code multi-angle code review workflow.
   - `/simplify`: Run the 4-angle code cleanup and refactoring pipeline.
   - `/security`: Run the senior security vulnerability analysis.
2. **Python API**:
   ```python
   from kratos_agent.core.prompt_library import prompt_library

   # Search prompts
   matches = prompt_library.search_prompts("code review")

   # Get subagent instructions
   subagent_prompt = prompt_library.get_subagent_prompt("explore")
   ```
