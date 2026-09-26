# Subsystem: CLI, Interactive Shell & Runtime Bootstrap
## Files: `src/kratos_agent/cli.py`, `src/kratos_agent/main.py`

Source Files:
- [`src/kratos_agent/cli.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/cli.py)
- [`src/kratos_agent/main.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/main.py)

---

### 1. Architectural Purpose & Overview

The entry points bootstrap Kratos, parse command-line arguments, configure logging, initialize the harness kernel, and launch either the interactive terminal prompt, headless mission execution, or the web server.

```
                         ┌──────────────────────┐
                         │      Entry Point     │
                         │(kratos / uv run ...) │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   main.py (Runtime)  │
                         │   - Env bootstrapping│
                         │   - Brain init       │
                         │   - Kernel presets   │
                         └──────────┬───────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         │                          │                          │
         ▼                          ▼                          ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  cli.py (Shell)  │      │  Web Server      │      │ Headless Mission │
│Interactive REPL  │      │FastAPI on :8000  │      │Single execution  │
│Slash commands    │      │Live WebSocket    │      │and exit          │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

---

### 2. Interactive Slash Commands in `cli.py`

The interactive CLI shell supports rich slash commands:

| Command | Arguments | Description |
|---|---|---|
| `/help` | - | Displays help menu with all commands and hotkeys |
| `/tools` | - | Displays table of all loaded and self-forged tools |
| `/plugins` | - | Displays table of active harness plugins and states |
| `/create-tool` | `<description>` | Autonomously forges and sandboxes a new Python tool |
| `/model` | `[model_id]` | Shows current model or switches to a different model |
| `/mode` | `[sovereign/supervised]` | Toggles between autonomous and supervised approval |
| `/skills` | `add/list/show/remove` | Manages skills loaded from URLs or local folders |
| `/memory` | `view/clear/search` | Inspects or manages persistent memory |
| `/doctor` | - | Runs full CCS and environment diagnostic preflight |
| `/live` | - | Launches real-time voice, vision, and avatar session |
| `/web` | `[port]` | Launches the FastAPI web server and opens the browser UI |
| `/clear` | - | Clears terminal screen and conversation buffer |
| `/exit` | - | Gracefully terminates Kratos session |

---

### 3. Bootstrap Flow in `main.py`

When Kratos boots:
1. **Environment Setup**: Calls `load_dotenv()` and configures UTF-8 standard output for Windows (`sys.stdout.reconfigure(encoding="utf-8")`).
2. **Brain Initialization**: Loads default provider and tests gateway connectivity with proxy bypassing (`trust_env=False`).
3. **Harness Kernel Spin-Up**: Applies the configured preset (`sovereign` or `full`), loading foundational plugins (`tools`, `memory`, `audit`, etc.).
4. **Tool Discovery**: Adapts curated tools from `tools_list.json` and `tools.py` into the authoritative `ToolRegistry`.
5. **Session Routing**: Branches into REPL, web server, or headless execution loop based on CLI flags.
