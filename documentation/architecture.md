# Architecture and Request Lifecycle

## System boundaries

Kratos has two execution backends that share the same product concepts:

- **Local Python runtime:** `src/kratos_agent/main.py`, `core/`, `brain/`, `web/`, and `tui/`. It can mutate the local workspace and run local commands.
- **Cloudflare edge runtime:** `worker.js` plus `functions/api/[[path]].js`. It stores a virtual workspace and telemetry in D1 and streams responses from the configured model gateway.
- **React console:** `frontend/src/`. It consumes the API, renders chat, sessions, tools, SQL results, and trace events.

## Local autonomous turn

```text
CLI or HTTP POST /api/chat
  -> KratosRuntime.invoke()
  -> AgentLoop.run()
  -> intent classification
  -> optional dynamic ExecutionPlan
  -> ContextBuilder.assemble()
  -> BrainAdapter.complete()
  -> tool-call extraction
  -> ToolRegistry.execute()
  -> approval and workspace safety checks
  -> side-effect tracking and RuntimeEvent publication
  -> VerificationManager.verify_workspace()
  -> session/event persistence
  -> final reply or SSE events
```

`AgentLoop.run(history, allow_tool, max_steps=24, resume_plan=None)` is the controlling loop. A `continue`, `resume`, or `/continue` user message can resume a paused plan. Cancellation is checked at tool boundaries, so an in-flight subprocess or HTTP request is not forcibly interrupted by the loop itself.

## Event flow

`RuntimeEvent` objects are sent to the runtime emitter and the global `event_bus`. The local TUI subscribes to the bus. The local web server subscribes for an individual SSE request. The event store writes a durable JSONL trace and can also mirror records to D1. Important event families include:

- turn/agent lifecycle: started, resumed, paused, completed, failed;
- planning: understanding, planning, plan created/updated, task started/updated/completed;
- model: request assembled, token received, model completed;
- tools: requested, started, completed, failed;
- workspace: file inspected/created/modified and command completed;
- verification: started and completed;
- compaction and latency diagnostics.

## Permission flow

1. `ToolRegistry._validate` checks object shape, required properties, and `additionalProperties: false`.
2. `KratosRuntime._allow_tool` maps tool permissions to read/write/execute policy.
3. `ApprovalGate` applies `suggest`, `auto-edit`, or `full-auto`.
4. File writes are resolved under the configured workspace; paths escaping it are rejected.
5. Shell commands are checked against the destructive-command blocklist before optional approval prompting.

## Normal chat versus agent mode

Normal chat uses the same gateway family but does not need the autonomous tool loop. Agent mode enables planning, tools, mutations, command execution, and verification. The browser's agent-mode password is checked by the web endpoint; the local Python runtime's approval mode is a separate policy layer.

## Persistence paths

- `.kratos/sessions/<session-id>/` contains local session/event artifacts.
- `.kratos/settings.json` stores the selected approval mode.
- `.kratos/kratos_d1.db` is the local D1-compatible SQLite mirror when configured.
- Cloudflare D1 stores `sessions`, `turns`, `agentic_events`, `commands`, and `workspace_files`.

## Edge request lifecycle

`worker.js` initializes the schema when a D1 binding exists, handles CORS, routes `/api/*` to `handleApi`, and delegates non-API requests to `env.ASSETS`. The Worker uses an in-memory request-local execution context plus D1-backed session and virtual-file persistence. `functions/api/[[path]].js` is the Cloudflare Pages adapter for the same API handler.
