# Complete File Catalog

This catalog accounts for the repository files relevant to source, configuration, runtime, deployment, and tests. Cache/build artifacts such as `__pycache__`, `.pytest_cache`, `.venv`, `.wrangler`, and `frontend/node_modules` are generated and intentionally excluded.

## Root

| File | Role |
| --- | --- |
| `README.md` | User-facing overview, quickstart, commands, architecture, deployment, and feature claims. |
| `KRATOS.md` | Project memory/architecture notes maintained by Kratos. |
| `pyproject.toml` | Python package metadata, dependencies, and CLI entry points. |
| `requirements.txt` | Alternate Python dependency list. |
| `uv.lock` | Locked Python dependency resolution. |
| `.env.example` | Environment variable template. |
| `.gitignore` | Ignored secrets, caches, builds, and generated artifacts. |
| `package.json` | Root Node/Cloudflare scripts and dependencies. |
| `worker.js` | Cloudflare Worker API, D1 schema, edge tools, and streaming runtime. |
| `worker-configuration.d.ts` | Worker environment/type declarations. |
| `wrangler.json` | Cloudflare deployment configuration. |
| `wrangler.toml.example` | Alternate Wrangler configuration template. |
| `kratos_entry.py` | PyInstaller/runtime bootstrap. |
| `kratos_agent.spec` | PyInstaller analysis, data files, hidden imports, and executable definition. |
| `build_exe.py` | Python Windows executable build orchestration. |
| `build_exe.ps1` | PowerShell executable build wrapper. |
| `build.bat` | Command Prompt executable build wrapper. |
| `kratos.ico`, `kratos_banner.png`, `kratos_banner.jpg` | Executable/UI branding assets. |

## Existing docs

| File | Role |
| --- | --- |
| `docs/architecture.md` | Existing architecture notes. |
| `docs/cloudflare_d1_setup.md` | D1 setup, migration, and web-console instructions. |
| `docs/kratos_web_ui.png` | Web UI screenshot. |

## Python packages

### `src/kratos_agent`

| File | Role |
| --- | --- |
| `__init__.py` | Package exports and main entry delegation. |
| `__main__.py` | `python -m kratos_agent` bootstrap. |
| `main.py` | `KratosRuntime` composition root and autonomous invocation. |
| `cli.py` | Interactive CLI, slash commands, completion, and launch modes. |

### `brain`

`__init__.py` public exports; `config.py` gateway/environment resolution; `client.py` HTTP transport; `chat_model.py` LangChain adapter and tool parser; `brain.py` simple LLM factories; `fetch_model.py` compatibility exports.

### `core`

`agent_loop.py` execution loop; `approval_mode.py` permission policy; `background_runner.py` async tasks; `compactor.py` context compression; `context_pipeline.py` prompt assembly; `d1_client.py` local/remote D1; `d1_schema.sql` schema; `event_bus.py` event fan-out; `event_store.py` durable traces; `git_tools.py` git operations; `hooks.py` tool hooks; `instruction_engine.py` instruction layers; `latency_tracker.py` timing metrics; `mcp_runtime.py` MCP integration; `memory.py` sessions; `planner.py` intent/plans; `project_memory.py` KRATOS.md context; `prompt_library.py` prompt search; `provider_runtime.py` model adapter; `reloader.py` hot reload; `runtime_contracts.py` shared types; `skills.py` skill manager; `subagents.py` child agents; `task_manager.py` task state; `tool_runtime.py` validated registry; `verification_manager.py` checks; `workspace_tracker.py` side effects.

### `tui`

`completion_view.py` final response cards; `debug_panel.py` step/event/latency panels; `events.py` RuntimeEvent-to-StepRecord translation; `live_renderer.py` Rich live display wrapper; `status_bar.py` model/session/progress status; `stream_printer.py` non-TTY output helpers; `__init__.py` TUI exports.

### `utils`

`tools.py` built-in handlers; `tools_list.json` tool manifest; `tool_creator.py` dynamic tool forging; `step_tracker.py` Rich progress state; `__init__.py` utility exports.

### `web`

`server.py` local threaded HTTP/SSE server; `highlighter.js` vendored syntax-highlighting runtime; `highlighter.json` language metadata.

## Frontend

`frontend/index.html` shell; `frontend/package.json` scripts/dependencies; `frontend/vite.config.js` build/proxy; `frontend/README.md` frontend notes; `frontend/src/main.jsx` mount; `App.jsx` orchestration; `App.css` app styles; `index.css` theme/global styles; `components/AgentArena.jsx`, `AgentHud.jsx`, `MarkdownRenderer.jsx`, `Modals.jsx`, `Navbar.jsx`, `RecruiterStrip.jsx`, `SessionsExplorer.jsx`, `SqlPlayground.jsx`, and `TraceReplay.jsx` UI surfaces; `public/highlighter.js` and `highlighter.json` browser highlighting assets; `public/fonts/` local fonts.

## API adapter

`functions/api/[[path]].js` is the Cloudflare Pages catch-all adapter that imports Worker CORS/schema/API helpers and exposes them through `onRequest(context)`.

## Tests

The 16 test modules are cataloged in [testing-and-build.md](testing-and-build.md), grouped by brain transport, planner/task state, runtime/tool loops, event/TUI UX, persistence, latency/verification, and web streaming.

## Generated and local state

`.kratos/` contains project memory, prompts, skills, session traces, settings, MCP configuration, and local D1 data. `.env` contains secrets. Build outputs (`dist`, `build`), caches, and dependency directories are not source documentation targets.
