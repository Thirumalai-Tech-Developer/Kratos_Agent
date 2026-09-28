# Codebase map

This map lists active runtime paths. The former provider adapter and Gemini mission-router trees have been removed.

| Area | Current responsibility |
| --- | --- |
| `src/kratos_agent/sdk/` | First-party gateway client, SSE parsing, tool-call values, and public agent facade. |
| `src/kratos_agent/brain/` | Gateway configuration and compatibility facade over the SDK. |
| `src/kratos_agent/main.py` | Application composition, model/tool loop wiring, risk checks, and speech directive dispatch. |
| `src/kratos_agent/core/agent_loop.py` | Bounded Kratos completion/tool continuation, planning, and evidence checks. |
| `src/kratos_agent/core/context_pipeline.py` | Instructions, history, schemas, and request budgeting. |
| `src/kratos_agent/core/tool_runtime.py` | JSON schemas, argument validation, permissions, and tool execution. |
| `src/kratos_agent/core/risk_policy.py` | Direct-request and target checks for high-consequence tool actions. |
| `src/kratos_agent/core/verification_manager.py` | Outcome assertions and evidence-based completion. |
| `src/kratos_agent/core/mcp_runtime.py` | MCP configuration, server lifecycle, and namespaced discovery. |
| `src/kratos_agent/core/harness/` | Runtime presets and tools, memory, audit, context, and creator plugins. |
| `src/kratos_agent/live/` | Local speech recognition, optional Gemini speech output, and screen/camera capture. |
| `src/kratos_agent/output/` | Marked speech directives and local voice helpers. |
| `openpets/kratos-companion/` | OpenPets SDK plugin source and install notes. |
| `tests/` | SDK, agent loop, risk, evidence, MCP, CLI, live speech, web, and persistence coverage. |

For contracts and data flow, see [`architecture.md`](architecture.md). For first-party SDK details, see [`AGENT_BACKENDS.md`](AGENT_BACKENDS.md).
