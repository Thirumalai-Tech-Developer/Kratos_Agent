# Kratos Agent

Kratos Studio combines the Kratos desktop and coding agent with the current OmniRoute gateway and dashboard. Kratos owns planning, tools, permissions, task state, verification, and memory for Kratos tasks. OmniRoute owns provider connections, configured model or combo routing, compression, quotas, and its native feature pages and agents.

## Runtime boundaries

| Component | Responsibility |
| --- | --- |
| Kratos SDK | Typed completions, streaming, structured tool calls, and same-endpoint retries through the supervised local OmniRoute gateway. |
| OmniRoute | Provider routing, fallback, compression, quotas, dashboard, APIs, and native agent features. Kratos requests opt out of OmniRoute memory and skill injection. |
| Agent loop and harness | Planning, tool execution, memory, audit events, permission checks, and evidence-based completion. |
| `computer-use` MCP | Desktop and browser actions, subject to Kratos tool policy. |
| Gemini Live | Optional text-to-speech only. Kratos sends only text enclosed by `[[speak]]...[[/speak]]`; Gemini receives no user audio, video, screen frames, tools, or reasoning prompts. |
| Local Windows speech | System.Speech recognition turns spoken requests into text for the Kratos agent. SAPI is the local speech fallback. |
| OpenPets | Animated desktop companion and speech bubble for approved spoken phrases. |

If the gateway is unavailable, the task reports a visible model error. Kratos retries its configured endpoint and model ID; any provider fallback inside a configured OmniRoute combo remains OmniRoute's responsibility.

## Setup

Requirements: Python 3.12 or 3.13, Node.js 20+ for OmniRoute and the built-in MCP servers, and the OpenPets desktop app if you use the animated companion.

1. Install dependencies with `uv sync`.
2. Build the bundled frontends and gateway once with `uv run kratos-studio setup`.
3. Start the unified app with `uv run kratos-studio run --workspace .`. Open `http://127.0.0.1:20128/dashboard/kratos`.
4. Read the initial dashboard password from `.kratos/studio/gateway/studio-secrets.json`. Keep that file private. For an existing OmniRoute store, use the offline import procedure in [Studio operations](integration/STUDIO_OPERATIONS.md); the imported database keeps its original login password.
5. Configure a model or combo in the OmniRoute dashboard and set its exact ID for Kratos:

   ```dotenv
   KRATOS_MODEL=<exact OmniRoute model or combo ID>
   KRATOS_API_KEY=<OmniRoute API key, if required by your endpoint>
   ```

The launcher supplies `KRATOS_BASE_URL` and starts both local services. For the terminal interface, run `uv run kratos-studio run --cli --workspace .` (or `uv run kratos --cli --workspace .`). It connects to a ready gateway on the selected port, or starts its own gateway and stops it when the CLI exits. Use `uv run kratos-studio setup --cli` for a gateway-only installation without building the agent web frontend. Setup prepares dependencies; `run --cli` opens the terminal agent.

`KRATOS_MODEL` is preferred. Existing `.env` files may keep using `BRAIN_MODEL`; `KRATOS_MODEL` takes precedence when both are set. Kratos does not guess an ID or silently choose another model when the gateway or configured model is unavailable. An OmniRoute combo may route among its configured compatible providers.

Optional speech output uses `GEMINI_API_KEY` or `GOOGLE_API_KEY` and `KRATOS_LIVE_ENABLED=true`. Without Gemini credentials, only marked phrases use local Windows SAPI output. Speech recognition remains local. Set `KRATOS_COMPUTER_USE_MCP=false` or `KRATOS_OPENPETS_MCP=false` to disable those built-in MCP servers.

## First-party Python SDK

```python
from kratos_agent.sdk import KratosAgent, KratosClient

client = KratosClient()
completion = client.complete({
    "model": "your-configured-kratos-model",
    "messages": [{"role": "user", "content": "Say hello."}],
    "stream": False,
})
print(completion.text)

agent = KratosAgent()
print(agent.run("Inspect this repository and explain its entry point."))
```

The SDK implements the existing gateway's `/v1/chat/completions` contract directly. It does not import model-provider agent SDKs. Tool calls are returned as typed `KratosToolCall` values, then executed by the guarded Kratos agent loop.

## Speech directives

Kratos displays the full answer with directive markers removed. It speaks only valid paired phrases:

```text
The task is complete. [[speak]]I finished and verified the task.[[/speak]] The report is saved in the workspace.
```

Unmarked, unmatched, or malformed speech tags do not reach Gemini or local TTS. The approved phrase is also sent to the OpenPets speech bubble when its MCP server is connected.

Load the companion plugin from `openpets/kratos-companion/` in OpenPets through **Plugins → Developer Mode → Load unpacked plugin folder**. Keep it enabled to get roaming, edge-climbing, reactions, and speech bubbles; Kratos does not install or enable the separate OpenPets desktop plugin automatically.

## Safety and evidence

- Tool schemas are validated before dispatch, and tool results return to the model loop.
- Write targets are checked against the workspace and approval mode.
- External sends/posts, destructive actions, purchases/bookings, account/security changes, and system installs require a direct user request with concrete targets supplied in the call.
- A tool start or success string is not proof of a result. Observable tasks require evidence before Kratos reports completion.
- Browser assertions are checked against live browser state before they count as verification evidence.
- MCP tools use the same permissions and evidence checks as built-in tools.

## Development

```powershell
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
```

Key code areas:

- `src/kratos_agent/sdk/`: first-party gateway and agent APIs.
- `src/kratos_agent/core/agent_loop.py`: planning, model/tool cycles, and completion checks.
- `src/kratos_agent/core/tool_runtime.py`: tool registry, validation, and execution boundary.
- `src/kratos_agent/core/risk_policy.py`: significant-consequence action gate.
- `src/kratos_agent/core/verification_manager.py`: evidence collection and completion gate.
- `src/kratos_agent/live/`: local speech input, speech output, and companion UI.
- `src/kratos_agent/core/mcp_runtime.py`: MCP server lifecycle and discovery.

The maintained documentation index is [`docs/README.md`](docs/README.md). Detailed contracts live in [`docs/architecture.md`](docs/architecture.md), [`docs/AGENT_BACKENDS.md`](docs/AGENT_BACKENDS.md), [`docs/GEMINI_LIVE.md`](docs/GEMINI_LIVE.md), and [`docs/tools-and-data.md`](docs/tools-and-data.md).
