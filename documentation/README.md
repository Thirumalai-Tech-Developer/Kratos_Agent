# Kratos Agent Documentation

This folder is the developer reference for the Kratos Agent repository. It documents the implementation currently present in the workspace, including Python runtime modules, the local web server, the Cloudflare Worker API, the React console, tools, configuration, build scripts, and tests.

## Start here

- [Architecture and request lifecycle](architecture.md)
- [Python runtime reference](python-reference.md)
- [Brain and model gateway reference](brain-reference.md)
- [Tools, memory, persistence, and data contracts](tools-and-data.md)
- [Web servers and API reference](web-api.md)
- [Frontend reference](frontend-reference.md)
- [Testing, configuration, and build reference](testing-and-build.md)
- [Complete file catalog](file-catalog.md)

## Supported entry points

| Entry point | Purpose |
| --- | --- |
| `uv run kratos` | Start the local web console. |
| `uv run kratos --cli` | Start the interactive terminal UI. |
| `uv run kratos "prompt"` | Run a one-shot request. |
| `npm run dev --prefix frontend` | Run the Vite frontend with `/api` proxied to port 7860. |
| `npx wrangler deploy` | Deploy the Worker and built frontend assets. |

## Documentation conventions

- Paths are repository-relative.
- Python signatures are shown with the arguments that callers can provide; `**kwargs` are described where they are accepted by an adapter or generated tool.
- The implementation is the source of truth when README claims and code differ. In particular, local Python defaults and Worker defaults are documented separately.
- `.env` values and API keys are configuration inputs, never documentation values to commit.

## Runtime at a glance

1. The CLI or web server creates or reuses `KratosRuntime`.
2. `ContextBuilder` combines instructions, history, tool schemas, and workspace metadata.
3. `BrainAdapter` and `BrainClient` call an OpenAI-compatible gateway and stream model output.
4. `extract_tool_calls_from_text` normalizes model tool-call formats.
5. `AgentLoop` validates permission, executes through `ToolRegistry`, tracks side effects, and verifies work.
6. `Memory`, `EventStore`, and optional D1 persistence record turns and events.
7. The local web server or Worker serializes events as SSE for the React console.
