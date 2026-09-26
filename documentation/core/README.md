# Subsystem: Core Runtime & Execution Engine
## Directory: `kratos_agent.core`

Source Directory: [`src/kratos_agent/core/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/)

---

### 1. Architectural Purpose & Overview

The `core` package contains Kratos' core runtime components: the autonomous agent loop, cognitive memory pipelines, verification engines, harness microkernel, and security permission gates.

```
src/kratos_agent/core/
├── agent_loop.py            # Main autonomous loop driving multi-turn execution
├── approval_mode.py         # Sovereign vs Supervised permission gating
├── background_runner.py     # Background thread & process task execution
├── cognitive_memory.py      # D1 & local scratchpad cognitive persistence
├── command_lint.py          # Shell command validation & security linting
├── compactor.py             # Context compression & memory budgeting
├── context_pipeline.py      # Multi-source prompt & context builder
├── d1_client.py             # Cloudflare D1 HTTP client with SQLite fallback
├── dispute.py               # Dispute arbitration for false completions
├── error_pipeline.py        # Centralized exception classification & recovery
├── errors.py                # Core domain error hierarchy
├── evidence.py              # Cryptographic & filesystem evidence contracts
├── framework_runtime.py     # Framework runtime adapters
├── harness/                 # Extensible plugin microkernel & presets
├── hooks.py                 # Lifecycle event interceptor registry
├── instruction_engine.py    # System instruction generation
├── latency_tracker.py       # Latency telemetry (TTFT, token rate, RTT)
├── mcp_runtime.py           # Model Context Protocol client & server transport
├── memory.py                # In-memory fact and KV store
├── planner.py               # Multi-phase agent planner & task decomposer
├── provider_runtime.py      # Dynamic LLM provider switcher
├── runtime_contracts.py     # Universal dataclasses (ToolCall, ToolResult, etc.)
├── skills.py                # Skills loader, markdown parser, & registry
├── task_manager.py          # Asynchronous long-running process manager
├── tool_runtime.py          # Authoritative ToolRegistry & permission tiers
└── verification_manager.py  # Authoritative verification gatekeeper
```

---

### 2. Module Documentation Links

- [`agent_loop.py.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/core/agent_loop.py.md): Autonomous loop, step execution, false completion gating.
- [`harness.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/core/harness.md): Harness microkernel, plugins (`creator`, `deepseek`, `memory`, `audit`, `tools`, `headroom`), crash isolation, lifecycle hooks, and CLI status.
- [`tool_runtime.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/core/tool_runtime.md): `ToolRegistry`, `ToolSpec`, `ToolPermission` (`READ`, `WRITE`, `EXECUTE`, `ADMIN`), and schema validation.
