# Development, configuration, and verification

## Runtime setup

The project supports Python 3.12 and 3.13. Install the application and development dependencies with `uv sync --extra dev`. The `kratos` and `kratos-agent` entry points launch the local application.

Set the exact reasoning model ID on the local gateway before making model requests:

```dotenv
KRATOS_BASE_URL=http://127.0.0.1:20128/v1
KRATOS_MODEL=<exact ID served by this gateway>
KRATOS_API_KEY=<optional gateway credential>
KRATOS_TIMEOUT=60
KRATOS_MAX_RETRIES=2
```

There is no model default. When the gateway is down or the ID is invalid, requests fail visibly; retries do not select another model.

Optional voice settings are `KRATOS_LIVE_ENABLED`, `KRATOS_LIVE_MODEL`, `KRATOS_LIVE_VOICE`, and `GEMINI_API_KEY`/`GOOGLE_API_KEY`. Gemini Live is used only for marked speech output. Voice recognition runs locally on Windows. The desktop companion runs in OpenPets.

The computer-use and OpenPets MCP servers are enabled by default. Disable them with `KRATOS_COMPUTER_USE_MCP=false` and `KRATOS_OPENPETS_MCP=false` respectively.

## Verification commands

```powershell
uv run pytest -q
uv run ruff check src tests
uv run kratos
```

The tests cover the Kratos SDK protocol, streaming tool calls, model locking, risk policy, verification evidence, MCP setup, and speech-directive boundaries. Network smoke tests are opt-in and require real service credentials.

## Build artifacts

`build_exe.py`, `build_exe.ps1`, `build.bat`, and `kratos_agent.spec` package the Windows CLI with PyInstaller. Run `uv run --extra build python build_exe.py`; the output is `dist/kratos-agent.exe` plus the loadable OpenPets plugin at `dist/openpets/kratos-companion/`. The frontend/Worker deployment uses the root JavaScript package and Wrangler configuration. These are separate from the local agent runtime and do not change its model routing.

Do not commit `.env`, gateway credentials, or generated session/event data under `.kratos/`.
