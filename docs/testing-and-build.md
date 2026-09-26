# Testing, Configuration, and Build Reference

## Python dependencies and commands

`pyproject.toml` requires Python 3.14 or newer and declares LangChain/OpenAI, HTTP, FastAPI/Uvicorn, Rich, prompt-toolkit, dotenv, Pillow, PyInstaller, and search dependencies. Entry points `kratos` and `kratos-agent` both call `kratos_agent.main:main`.

Recommended commands:

```powershell
uv sync
uv run python -m unittest discover tests
uv run python -m unittest tests/test_runtime.py
npm install --prefix frontend
npm run build --prefix frontend
```

## Test inventory

| Test module | Coverage |
| --- | --- |
| `test_brain_config.py` | Environment precedence, endpoint/model defaults, auth headers, timeout/retry parsing. |
| `test_brain_transport.py` | Request envelopes, HTTP errors, retries, streaming and tool-call transport. |
| `test_stream_response.py` | Incremental response/token behavior. |
| `test_tool_calling_loop.py` | Model tool-call extraction, execution, and follow-up loop. |
| `test_planner.py` | Intent classification and plan/task creation. |
| `test_dynamic_agent_planning.py` | Model-generated dynamic plans and runtime integration. |
| `test_task_manager.py` | Task state transitions, dependencies, serialization, and resume behavior. |
| `test_runtime.py` | Runtime composition, invoke flow, history, model/session changes, and permissions. |
| `test_agent_execution_ux.py` | Agent execution event/status UX and user-facing step behavior. |
| `test_false_completion.py` | Preventing completion claims when work or verification is incomplete. |
| `test_latency_and_verification_timing.py` | Request metrics, TTFT/durations, and verification timing. |
| `test_event_bus.py` | Subscription, publication, and listener behavior. |
| `test_live_renderer_wiring.py` | Event-to-TUI renderer wiring and live state updates. |
| `test_d1_client.py` | D1/local database connection and query behavior. |
| `test_d1_storage.py` | Persistence of sessions, turns, events, commands, and workspace state. |
| `test_web_live_chat.py` | Local web chat endpoints and live SSE behavior. |

The project currently uses `unittest` discovery even though a pytest cache may exist. Run the repository's chosen command before changing test infrastructure.

## Environment variables

| Variable | Purpose and precedence |
| --- | --- |
| `BRAIN_BASE_URL`, `CHAT_BASE_URL`, `OMNIROUTE_BASE_URL` | Base model gateway URL. |
| `CHAT_ENDPOINT`, `BRAIN_CHAT_URL`, `KRATOS_API_URL`, `OMNIROUTE_CHAT_URL` | Direct chat completion endpoint. |
| `MODEL_ENDPOINT`, `BRAIN_MODEL_URL` | Direct model listing endpoint. |
| `OMNI_KEY`, `BRAIN_KEY`, `KRATOS_API_KEY`, `OPENAI_API_KEY` | API key precedence. |
| `BRAIN_MODEL`, `OMNIROUTE_MODEL`, `KRATOS_MODEL` | Agent model precedence. |
| `NORMAL_MODE_MODEL` | Normal chat model. |
| `BRAIN_TIMEOUT`, `OMNIROUTE_TIMEOUT`, `KRATOS_TIMEOUT` | Request timeout. |
| `BRAIN_MAX_RETRIES`, `OMNIROUTE_MAX_RETRIES`, `KRATOS_MAX_RETRIES` | Retry count. |
| `AGENT_PASSWORD` | Web agent-mode password. |
| `KRATOS_APPROVAL_MODE` | Documented approval setting; the `ApprovalGate` persists the active value in `.kratos/settings.json`. |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_D1_DATABASE_ID`, `CLOUDFLARE_API_TOKEN` | Optional remote D1 mirror credentials. |
| `KRATOS_IMAGE_BANNER` | Enables optional image banner rendering in compatible terminals. |

Never commit `.env`. `.env.example` is a template only.

## Windows executable build

`build_exe.py`:

- `prepare_icon()`: generates `kratos.ico` from `kratos_banner.png` when missing.
- `run_build()`: runs PyInstaller against `kratos_agent.spec`, checks `dist/kratos-agent.exe`, and reports size/failure.

`build_exe.ps1` and `build.bat` are command wrappers. `kratos_agent.spec` collects `tools_list.json`, optional banner/prompts/skills, hidden imports, and `kratos_entry.py` into a console executable. `kratos_entry.py` is the frozen-build bootstrap.

## Cloudflare build/deploy

- Root `package.json` contains deployment convenience scripts.
- `wrangler.json`/`wrangler.toml.example` define Worker/static asset and D1 bindings.
- `worker-configuration.d.ts` describes generated Worker environment types.
- Build `frontend/dist` first, then deploy with Wrangler.

## Operational caveats

The Worker currently exposes broad CORS and an SQL endpoint; deployments should add authentication, query restrictions, and least-privilege D1 bindings. The local approval blocklist is useful defense in depth but is pattern-based, not a complete shell security model.
