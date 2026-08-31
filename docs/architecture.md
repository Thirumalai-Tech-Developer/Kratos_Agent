# Kratos runtime architecture

Kratos is an explicit agent runtime, not a single prompt wrapped around an LLM.
Every turn follows this pipeline:

```text
User input → Session history → Context Builder → Instruction Engine
          → Tool Registry → Model Adapter → Agent Loop
          → Tool Execution → Tool Result → Context Update → Model again → Final response
```

## Request contract and transparency

Before every model call, `ContextBuilder.assemble()` produces one inspectable request object:

| Field | Sent to model | Source |
| --- | --- | --- |
| `instructions` / `system` | Yes | independently registered system, developer, persona, project, and runtime modules |
| `messages` | Yes | session history, current request, model messages, and pruned tool results |
| `tools` | Yes | JSON schemas from built-in and MCP tool registries |
| `workspace` | Yes | current workspace path and runtime facts |
| `token_estimate` | Trace only | deterministic approximation used for budgeting |

`KratosRuntime.debug_context()` returns the registered instruction modules, exact redacted request snapshot, tool schemas, history, token estimate, and the latest event stream. Append-only events live at `.kratos/sessions/<session-id>/events.jsonl`; a request snapshot redacts common credential fields before persistence.

## Components and boundaries

- `instruction_engine.py` owns composable instructions. A persona or skill is an `InstructionModule`, not a concatenated global prompt.
- `context_pipeline.py` owns token budgeting, deterministic tool-result pruning, and transparent compaction checkpoints. Full outputs stay in the trace while only the model-facing copy is shortened.
- `tool_runtime.py` owns schemas, argument validation, permissions, time accounting, and conversion of exceptions into durable `ToolResult` values. A failure remains in the next model context.
- `provider_runtime.py` defines the provider-neutral `ModelAdapter` response contract. The OmniRoute adapter connects to `http://127.0.0.1:20128/v1/chat/completions` with proxy bypass (`trust_env=False`) and standard OpenAI-compatible message envelopes.
- `agent_loop.py` owns the bounded continuation loop. It has no provider, CLI, or LangChain orchestration dependency.
- `event_store.py` writes recovery/debug events as JSONL. Existing session files continue to provide CLI compatibility; the event log is the detailed replay record.
- `mcp_runtime.py` owns server configuration and namespaced dynamic tool discovery (`mcp__server__tool`). An MCP transport is injected rather than imported into core runtime code.
- `subagents.py` creates isolated histories and structured child results. It supports safe parallel fan-out through an injected isolated runner.

## Safety and extensions

Every tool has a capability (`read`, `write`, `execute`, `git`, or `network`). The runtime checks a resolved write target stays under the workspace, then delegates the human approval decision to the existing approval gate. `suggest` remains read-only for non-read tools. MCP tools use the same gateway.

Skills and hooks remain extension points. MCP servers are configured in `.kratos/mcp.json` (or a caller-selected path) and never require a core-loop modification. Provider-specific retries/fallback are confined to adapters; the loop records the resulting retry/error event and retains its state.

Example MCP configuration (the selected stdio/SSE transport supplies discovery):

```json
{
  "mcpServers": {
    "github": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"] }
  }
}
```

Discovered functions are always namespaced (`mcp__github__…`) and enter the same schema validation, approval, timing, trace, and failure-recovery path as built-in tools.

## Transport Layer

Kratos uses OmniRoute as its single model gateway (`http://127.0.0.1:20128/v1/chat/completions` with model `antigravity/gemini-3.7-flash-high`). The agent core remains completely provider-neutral.
