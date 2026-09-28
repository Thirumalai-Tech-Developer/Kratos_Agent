# Kratos Agent architecture

Kratos is one application-owned agent loop backed by one explicitly configured model on the local Kratos gateway. The gateway uses the existing OpenAI-compatible `/v1/chat/completions` HTTP shape, but the application uses its own `KratosClient`; there is no provider router or alternate reasoning model.

```text
Request -> instructions/context -> KratosClient -> validated tool calls
       -> risk/permission checks -> tools and MCP -> evidence gate -> response
```

## Runtime components

- `sdk/client.py` owns the gateway HTTP/SSE protocol, response parsing, retry policy, and typed tool calls.
- `sdk/agent.py` exposes the public `KratosAgent` facade.
- `core/agent_loop.py` runs the bounded plan, completion, tool execution, and continuation cycle.
- `core/context_pipeline.py` builds and budgets the model request.
- `core/prompt_builder.py` and `core/instruction_engine.py` build persistent system instructions and harness modules.
- `core/tool_runtime.py` validates tool schemas, arguments, permissions, and execution results.
- `core/risk_policy.py` gates significant external, destructive, financial, account, and system-changing actions.
- `core/verification_manager.py` checks outcome assertions and requires evidence for observable completion.
- `core/mcp_runtime.py` discovers configured MCP tools and the built-in computer-use and OpenPets servers.
- `core/harness/` applies always-on runtime presets, tools, memory, audit, and context plugins.
- `live/` provides local speech recognition, optional Gemini audio output, and OpenPets companion integration. It does not reason or execute tools.

## Model and outage contract

Set `KRATOS_MODEL` to the exact ID served by the local gateway. No model ID is selected automatically. Retries are limited to the same endpoint and configured model; an unavailable gateway fails visibly. Gemini Live can render approved speech phrases, but its availability does not affect Kratos reasoning or task execution.

## Safety and evidence

All tool calls pass through the same registry and policy checks, including MCP tools. External communication, destructive changes, financial actions, security/account changes, and system installation are treated as significant consequence. The runtime requires a direct user request and concrete targets in the call. Observable tasks are complete only when the configured assertion has evidence; browser assertions are checked against live browser state.

## Inspectable execution

`KratosRuntime.debug_context()` returns model, instructions, history, schemas, and the latest redacted request snapshot. Event records are stored under `.kratos/sessions/<session-id>/events.jsonl`; tool results and failures remain in the agent continuation context so Kratos can respond to what actually happened.
