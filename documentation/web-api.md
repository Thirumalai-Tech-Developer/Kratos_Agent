# Web Servers and API Reference

## Local Python server

`src/kratos_agent/web/server.py` implements a threaded `http.server` frontend for the local runtime.

- `get_web_dir() -> Path`: resolves the bundled web asset directory.
- `KratosWebHandler`: handles HTTP requests.
  - `do_OPTIONS()`: returns CORS preflight.
  - `do_GET()`: routes stats, telemetry, tools, sessions, session detail, events, or static assets; protects static paths from traversal and falls back to `index.html` for SPA routes.
  - `do_POST()`: parses JSON and routes chat SSE, synchronous chat, session creation, SQL, and agent-mode authentication.
  - `do_DELETE()`: deletes sessions by ID.
  - `_handle_chat_sse(payload)`: subscribes to runtime events, emits SSE frames, runs the runtime in a worker thread, and sends the final reply/error.
  - `_handle_chat_sync(payload)`: executes the same request without SSE.
  - `_handle_auth_agent_mode(payload)`: validates the configured agent password.
  - `_handle_get_stats()`, `_handle_get_telemetry()`, `_handle_get_tools()`: expose diagnostics and registry data.
  - `_handle_get_sessions()`, `_handle_get_session_detail(session_id)`, `_handle_create_session(payload)`, `_handle_delete_session(session_id)`: manage persisted sessions.
  - `_handle_get_events(session_id=None)`: returns all or session-scoped trace events.
  - `_handle_sql_query(payload)`: executes a read query through the D1 client.
  - `_send_json(data, status=HTTPStatus.OK)`: serializes JSON with CORS and no-cache headers.
- `KratosServer(ThreadingHTTPServer, ...)`: stores runtime/server context.
- `start_server(host="127.0.0.1", port=7860)`: starts the threaded server and serves the console.

### Local endpoints

| Method | Path | Response/use |
| --- | --- | --- |
| `GET` | `/api/stats` | Session/turn/event counts and database metadata. |
| `GET` | `/api/telemetry` | Latency and runtime telemetry. |
| `GET` | `/api/tools` | Registered tool specifications. |
| `GET` | `/api/sessions` | Session summaries. |
| `GET` | `/api/sessions/<id>` | Session metadata and turns. |
| `POST` | `/api/sessions` | Creates a session from JSON title/model inputs. |
| `DELETE` | `/api/sessions/<id>` | Removes a session. |
| `GET` | `/api/events` or `/api/events/<id>` | Trace events. |
| `POST` | `/api/chat` | SSE chat/agent execution. |
| `POST` | `/api/chat/sync` | JSON chat/agent execution. |
| `POST` | `/api/query` | D1 SQL query. |
| `POST` | `/api/auth/agent-mode` | Password check. |

Chat payloads accept `prompt`, `message`, or `query`, optional `session_id`, `mode`, `agent_mode`, and `agent_password`. SSE `data:` frames may contain `session_id`, `token`, `reasoning_token`, `step`, `tool_call`, `tool_result`, `result`, `reply`, or `error`.

## Cloudflare Worker

`worker.js` exports the default `fetch(request, env, ctx)` handler plus `getSchemaSql`, `corsHeaders`, `jsonResponse`, and `handleApi`.

- `fetch` handles OPTIONS, initializes D1, dispatches `/api/*`, and serves `env.ASSETS` for everything else.
- `corsHeaders()` returns permissive CORS headers used by the console.
- `jsonResponse(data, status=200)` serializes JSON with CORS and no-cache headers.
- `formatToolActionLabel(name, args={})` creates compact status labels.
- `handleApi(request, env, url)` routes Worker API endpoints and normalizes request errors.
- Worker-specific helpers implement session CRUD, event replay, SQL, model requests, tool execution, virtual workspace operations, and SSE framing. Tool metadata is declared in `TOOLS_LIST` with permission and timeout fields.

The edge implementation is not a shell sandbox. `run_terminal_command` and other execution tools are subject to the Worker implementation and environment bindings; do not assume local Python subprocess semantics on the edge.

## Cloudflare Pages adapter

`functions/api/[[path]].js` exports `onRequest(context)`. It handles CORS and schema initialization, then delegates all API behavior to the Worker exports. This keeps Pages and Worker deployments on the same route implementation.

## D1 query expectations

The React SQL playground sends `{query}` to `/api/query`. Presets are read-only `SELECT` statements over `sessions`, `turns`, `agentic_events`, and `commands`. Treat arbitrary SQL as privileged input and apply deployment-specific authorization before exposing the endpoint publicly.
