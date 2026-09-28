# Agent execution and harness

Kratos has one reasoning client and one execution loop. Harness presets can change context, tool availability, and always-on plugins; they cannot select another model or bypass the execution boundary.

```text
Kratos model response
  -> parse structured tool calls
  -> validate schema and arguments
  -> check approval and risk policy
  -> execute built-in or MCP tool
  -> store result and collect evidence
  -> continue with the same configured model
```

## Harness responsibilities

- `standard`, `code`, `minimal`, and `creator` presets shape context and tool surfaces.
- `ToolsPlugin` exposes built-in tools and MCP discovery to the runtime.
- `MemoryPlugin` attaches persistent task/session memory.
- `AuditPlugin` writes execution traces under `.kratos/trace`.
- `HeadroomPlugin` may reduce request context while preserving the original tool output in trace state.
- `CreatorPlugin` enables bounded tool-creation workflows.

The Kratos gateway client retries eligible transient errors only against the same configured model. Provider selection, provider failover, and framework subprocess delegation are not part of the harness.

## Status and evidence

The model response alone is not completion evidence. Workspace files, browser state, command exit codes, and other capability-specific observations are recorded in the runtime. The verification manager evaluates declared outcome assertions before the loop may report a verified result.
