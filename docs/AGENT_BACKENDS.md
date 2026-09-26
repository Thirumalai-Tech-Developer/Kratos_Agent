# KRATOS BEAST // AGENT BACKENDS & SDK ADAPTERS

## Implementation Details for Specialist Execution Runtimes

---

## 1. Native Kratos Engine (`kratos_native`)
- **Location**: `src/kratos_agent/providers/kratos_native.py`
- **Role**: Hermetic baseline backend. Always enabled and requires no external third-party SDK dependencies.
- **Capabilities**:
  - Full local tool calling using Kratos' canonical `ToolRegistry`
  - Subprocess shell execution with output streaming
  - Workspace file mutations and syntax validation
  - Local git operations and patch application

---

## 2. OpenAI Codex SDK Adapter (`codex`)
- **Location**: `src/kratos_agent/providers/codex/`
- **Key Capabilities**:
  - Interactive turn steering via thread messaging
  - Asynchronous turn interruption
  - Streaming token deltas (`TOKEN_DELTA`) and message boundaries
  - Image input for visual UI inspection
- **Adapter Mapping**: Translates Kratos `ToolRegistry` into OpenAI function calling specifications with strict type validation.

---

## 3. Anthropic Claude Agent SDK Adapter (`claude`)
- **Location**: `src/kratos_agent/providers/claude/`
- **Key Capabilities**:
  - Native Model Context Protocol (MCP) bridge
  - Agentic subagent delegation
  - Lifecycle hooks for pre-tool and post-tool evaluation
  - Streaming content blocks and thinking deltas (`REASONING_DELTA`)
- **Adapter Mapping**: Converts Kratos tools into Anthropic tool schemas with `input_schema`.

---

## 4. Moonshot Kimi Agent SDK Adapter (`kimi`)
- **Location**: `src/kratos_agent/providers/kimi/`
- **Key Capabilities**:
  - High-throughput streaming execution
  - Interactive tool call approval gates
  - Long-context processing (up to 200,000 tokens)
  - MCP tool interoperability

---

## 5. DeepSeek Harness Adapter (`deepseek`)
- **Location**: `src/kratos_agent/providers/deepseek/`
- **Isolated Home**: Resides hermetically in `.kratos/providers/deepseek` to isolate runtime configs, virtualenvs, and JSON-RPC pipes.
- **Key Capabilities**:
  - Persistent JSON-RPC daemon lifecycle
  - Patch generation and workspace modification
  - Long-running execution sessions
  - Plugin subsystem integration

---

## 6. Google Antigravity SDK Adapter (`antigravity`)
- **Location**: `src/kratos_agent/providers/antigravity/`
- **Feature Flag**: Controlled via `KRATOS_ENABLE_ANTIGRAVITY=true` or configuration flag.
- **Capability Probing**: Probes the installed environment for verified API surfaces. If unsupported or unconfigured, gracefully reports `HealthStatus.DISABLED` rather than faking compatibility.
