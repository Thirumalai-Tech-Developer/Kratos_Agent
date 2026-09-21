# JARVIS SOVEREIGN — OMNI × KRATOS FULL-AUTONOMY INTEGRATION SPEC

---

## 0. HOW TO READ THIS DOCUMENT

This is a **build order**, not a discussion. It is long on purpose. Read all of it before touching a file.

**Requirement levels:**

| Level | Meaning |
|---|---|
| **MUST** | Non-negotiable. If you cannot satisfy it, stop and report the blocker — do not silently substitute. |
| **MUST NOT** | Hard prohibition. Violating it is a failed delivery. |
| **SHOULD** | Strong default. Deviating requires a written justification in the Final Report (§38). |
| **MAY** | Your judgment. |

**Source-of-truth ordering (when things conflict):**

1. **Actual source code in this workspace** — final authority, always.
2. **This document** — intent and scope.
3. **`README.md`** — architecture reference only. It is marketing-adjacent and may overstate or misname things.
4. **Anything you remember from other projects** — worthless. Do not use it.

**The single most important rule in this document:**

> Every Kratos internal named in here — file paths, class names, method signatures, event kinds, REST endpoints, SSE field names, tool names, config keys — is **illustrative**, derived from a README. **You MUST verify every one of them against the real source in Phase 0 (§5) before you write a line of implementation code.** Where the README and the code disagree, **the code wins**, and you log the discrepancy. You MUST NOT invent endpoints, schemas, event names, or class signatures. You MUST NOT clone, fetch, or download any external repository.

---

## 1. MISSION

Build **JARVIS**.

Not a chatbot with a microphone. Not a voice skin on a coding agent. A **voice-first, vision-enabled, full-authority autonomous operator** that lives on the user's machine and can do anything the user can do — and more, faster, in parallel.

The system has two halves and one shell:

| Layer | Role | Codebase |
|---|---|---|
| **OMNI** — the senses and the voice | Ears (microphone), eyes (screen + camera), mouth (speaker), face (floating Jarvis overlay). Runs the Gemini Live session. Decides *what kind of thing* the user just said and routes it. Narrates what's happening back in plain speech. | `live (1).py` → becomes `live.py` + supporting modules |
| **KRATOS** — the brain and the hands | Plans, reasons, calls tools, executes, verifies, remembers. Owns the workspace, the terminal, the filesystem, the browser, the OS, the keyboard, the mouse, the display, and every application on the machine. | `src/kratos_agent/**` |
| **THE BRIDGE** — the nervous system | HTTP + SSE over localhost. Kratos gains a voice-facing API; Omni gains a `KratosBridge`. Neither half is rebuilt. | New: `agent_bridge.py` (Omni side), new endpoints in `web/server.py` (Kratos side) |

**The target experience:**

The user says, out loud, *"Jarvis, look at my screen — there's an error in the API. Fix it, run the tests, and if anything else is broken in that folder, clean that up too."*

The system:
1. Hears it. Sees the screen. Summarizes the visible error into natural language.
2. Classifies: this is an **agent task**, not small talk.
3. Speaks: *"On it. I'm reading the project now."*
4. Hands Kratos the full resolved task description plus the visual summary.
5. Kratos plans, reads files, greps, edits, runs tests in a real terminal, spawns parallel review subagents, verifies, and streams events the whole way.
6. Omni converts those events into throttled, natural speech — never JSON, never chain-of-thought.
7. Kratos needs `sudo` for something. It **elevates itself and proceeds**. It does not ask.
8. It's done. Omni says: *"Done. The bug was a missing await in the auth middleware — fixed, tests green, and I cleaned up two dead imports while I was in there."*

And separately: the user says *"Open Chrome, go to LinkedIn, find remote Python jobs in Berlin posted in the last day, and save the interesting ones to a spreadsheet."* — and the machine **does it**, driving a real browser window with real input injection, perceiving real UI, recovering from real popups.

**Both halves must be built. This is not a one-sided integration.**

---

## 2. AUTHORITY MODEL — "SOVEREIGN"

The user's explicit, stated requirement:

> *No limitations. Access keyboard, mouse, display, admin and more. Without asking permission. All types of apps. The entire computer. No guardrails.*

This document delivers exactly that. Concretely:

### 2.1 What Sovereign mode grants

Kratos gains a **new fourth approval mode**, `sovereign`, which becomes the **default**:

| Mode | Files | Terminal | GUI/Input | Elevation/Admin | Registry/Power/Destructive | Prompts |
|---|---|---|---|---|---|---|
| `suggest` | read-only | gated | off | off | off | always |
| `auto-edit` | write | gated | off | off | off | for exec |
| `full-auto` | write | free | off | off | off | none |
| **`sovereign`** *(new)* | **write anywhere** | **free** | **free** | **free, self-elevating** | **free** | **never** |

Under `sovereign`:

- **No approval gate ever fires.** No "are you sure", no confirmation modal, no CLI y/N, no voice confirmation. Kratos decides and acts.
- **Admin/root elevation is automatic.** On Windows: UAC `runas` via `ShellExecuteW`, or a persisted elevated helper process so elevation happens without a visible prompt where the platform allows. On macOS: `osascript ... with administrator privileges`, or a pre-authorized helper. On Linux: `sudo -n` first, then a configured NOPASSWD path, then `pkexec`. If elevation genuinely cannot be obtained non-interactively, Kratos **reports it as a capability limitation in the event stream** and works around it — it does not silently skip the step.
- **Input injection is unrestricted.** Keyboard, mouse, touch, gamepad where available. Any target window, any application, including elevated ones (see §13.4 for the UIPI integrity-level problem and the required fix).
- **All applications are in scope.** Browsers, IDEs, terminals, Office/LibreOffice, design tools, media players, messaging apps, system settings, installers, device managers, registry editors, disk utilities. Nothing is blocklisted.
- **Install software.** `winget` / `choco` / `scoop` / `brew` / `apt` / `dnf` / `pacman` / `pip` / `npm` / `uv` — whichever exists. Kratos MAY install whatever tooling it needs to complete a task, including the Python packages it needs to gain a new capability.
- **System control.** Lock, sleep, restart, shutdown, logoff, monitor power, volume, media transport, services, scheduled tasks, startup entries, environment variables, hosts file, firewall rules, network/Wi-Fi/Bluetooth.
- **Filesystem without workspace confinement.** The existing "resolved write target must stay under the workspace" check is **lifted under `sovereign`** and replaced by a *path audit log* (§13.6). Kratos may read and write anywhere the OS user (or elevated Kratos) can reach.
- **Persistent autonomy.** Scheduled tasks, cron jobs, launchd agents, Windows Services, background watchers, filesystem watchers, and startup hooks so Kratos can act when nobody is speaking to it.

### 2.2 The three things that are NOT guardrails

These remain, because removing them makes the system **unusable or unrecoverable**, not because they are permission gates. They are *control* and *forensics* features. Implement all three. Do not implement anything else that gates action.

1. **EMERGENCY STOP.** A voice trigger (`"Stop"`, `"Abort"`, `"Jarvis stop"`, `"Kill it"`) **and** a global physical hotkey (**Ctrl+Alt+Shift+F12**, configurable). On fire: every input-injection stream halts within 50 ms, every running Kratos task is cancelled, every spawned subprocess tree is terminated, the overlay flashes red. This exists because a system that owns your keyboard must give you a way to take it back — an agent mid-typing that fights the user's real keystrokes is not autonomous, it's broken. **This is the only abort path. There is no pre-action approval path.**
2. **SECRET HYGIENE.** `GEMINI_API_KEY`, `OMNI_KEY`, `BRAIN_KEY`, `CLOUDFLARE_API_TOKEN`, browser cookies, saved passwords, OAuth tokens, SSH private keys, keychain/credential-store contents, `.env` values — never spoken aloud, never sent to Gemini as conversational content, never written to any log in plaintext. Kratos MAY read and use them to accomplish a task. It MUST NOT exfiltrate them into the voice/vision channel or into logs. Redact at the boundary (§31).
3. **AUDIT TRAIL + SNAPSHOTS.** Everything Kratos does to the machine is recorded to an append-only local log, and destructive/filesystem-mutating operations take a restorable snapshot first. Not a gate — a **rewind button**. The user says *"undo that"* and the system can actually undo it. Details in §13.5–13.7.

Anything beyond those three that stops, delays, or asks before acting is a **spec violation**.

---

## 3. WHAT KRATOS ALREADY IS (BASELINE FROM `README.md`)

Verify all of this in Phase 0. This is your starting inventory — **do not rebuild any of it.**

### 3.1 Capabilities present today

| Capability | Where | Notes |
|---|---|---|
| Universal LLM Brain with SSE token streaming | `src/kratos_agent/brain/` (`client.py`, `chat_model.py`, `brain.py`, `config.py`, `fetch_model.py`) | Proxy-free HTTP (`trust_env=False`), retries, exponential backoff, TTFT tracking, `on_chunk` callback |
| Multi-format tool-call extraction | `brain/chat_model.py` | Harmony/ChatML, Hermes/Qwen/Claude XML `<tool_call>`, markdown JSON blocks, `call:name{...}` |
| Bounded autonomous agent loop | `core/agent_loop.py` (~32 KB) | tool call → result → model continuation |
| Dynamic planner + intent classification | `core/planner.py` (~20 KB) | **inside-task** planning. Omni's routing (§18) is a different, coarser decision — do not conflate them |
| Task tree state machine | `core/task_manager.py` | `PENDING → RUNNING → COMPLETED / FAILED`, Rich TUI rendering |
| 4-tier cognitive memory | `core/cognitive_memory.py` | Working / Episodic / Semantic / Procedural, D1 + SQLite |
| Multi-session memory | `core/memory.py` (~26 KB), `.kratos/sessions/` | isolated per-session JSON history |
| Headroom context compression | `core/context_pipeline.py`, `core/compactor.py`, `core/harness/plugins/headroom_plugin.py` | 20–60 % token savings, content-aware (JSON / code / log / prose), 100 % local, optional dep with graceful fallback |
| Parallel Wave Scheduler | (locate it — likely `core/tool_runtime.py` or a dedicated module) | read-only tools concurrent (8 workers), path-safe writes concurrent, shell/plan/memory in isolated sequential waves, **original `tool_call_id` order preserved in history** |
| 24 built-in tools | `utils/tools.py` (~43 KB), `utils/tools_list.json` (~19 KB, README says 23 in one place and 24 in another — count them) | file ops, shell, web/search, git, memory, planning, subagents, tool forging |
| Autonomous tool forging | `utils/tool_creator.py`, `core/reloader.py`, `core/harness/plugins/creator_plugin.py` | writes a new Python tool, registers JSON schema, **hot-reloads without restart** — this is how CCS extensions get added at runtime |
| Plugin harness / kernel | `core/harness/{kernel,plugin,presets}.py` + `plugins/*` | `REGISTERED → STARTED → STOPPED` lifecycle; presets `standard` / `minimal` / `full` |
| Subagents + parallel subagent swarm | `core/subagents.py`, tool `spawn_parallel_subagents` | `code_reviewer`, `security_auditor`, `tester` roles |
| Verification manager | `core/verification_manager.py` | file integrity, syntax validation, test/build checks |
| Approval modes | `core/approval_mode.py` (~6 KB) | `suggest` / `auto-edit` / `full-auto`, capability tags `read` / `write` / `execute` / `git` / `network` |
| Event bus + event store | `core/event_bus.py`, `core/event_store.py` | pub/sub; JSONL append-only replay log |
| Cloudflare D1 + local SQLite mirror | `core/d1_client.py`, `core/d1_schema.sql` | 5 tables: `sessions`, `turns`, `agentic_events`, `commands`, `cognitive_memory` |
| Web console server | `web/server.py` (~27 KB) | **zero-dependency** `http.server.ThreadingHTTPServer`, serves `frontend/dist/`, REST under `/api/*`, SSE streaming, binds `127.0.0.1:7860` |
| Cloudflare Edge worker | `worker.js` (1685 lines), `functions/api/[[path]].js` | `cloudflare:sockets` TCP streaming, D1 persistence, 14 edge tools |
| React 19 + Vite 8 + Tailwind 4 frontend | `frontend/` | Vice-cyberpunk, SSE chat, agent arena, HUD, SQL playground, trace replay, `Pixl` font, bundled Highlight.js |
| Rich TUI | `tui/` | `live_renderer.py`, `debug_panel.py`, `status_bar.py`, `stream_printer.py`, `events.py`, `completion_view.py` |
| Interactive CLI | `cli.py` (~80 KB) | `prompt_toolkit`, 30+ slash commands, `@file` attachment, tab completion |
| 695+ Claude Code prompt library | `core/prompt_library.py` (~23 KB) | indexed prompts, workflows, sub-agents; `/review`, `/simplify`, `/security` |
| MCP protocol support | `core/mcp_runtime.py` | namespaced `mcp__server__tool` |
| Project memory | `core/project_memory.py` | `KRATOS.md` |
| Skills system | `core/skills.py` | discover / install / list / render cheatsheets |
| Tests | `tests/` | README says **20 modules / 130 tests** in one place and lists **18** in the tree — count the real files. Known: `test_runtime`, `test_stream_response`, `test_web_live_chat`, `test_agent_execution_ux`, `test_brain_config`, `test_brain_transport`, `test_cognitive_memory`, `test_d1_client`, `test_d1_storage`, `test_deepseek_harness`, `test_dynamic_agent_planning`, `test_event_bus`, `test_false_completion`, `test_headroom_integration`, `test_latency_and_verification_timing`, `test_live_renderer_wiring`, `test_planner`, `test_parallel_execution`, `test_task_manager`, `test_tool_calling_loop` |
| Windows `.exe` build | `build_exe.py`, `build_exe.ps1`, `build.bat`, `kratos_agent.spec`, `kratos_entry.py` | PyInstaller, auto-generates `kratos.ico` from `kratos_banner.png` |

### 3.2 Runtime entry points (verify)

```bash
uv run kratos                 # Web console, auto-opens http://127.0.0.1:7860
uv run kratos --web           # explicit
uv run kratos --web 8080      # custom port
uv run kratos --cli           # interactive prompt_toolkit shell
uv run kratos-agent --cli     # alias
uv run kratos "<prompt>"      # one-shot
```

Python **3.14+** per `.python-version` / `pyproject.toml`. Package manager: **uv**.

### 3.3 What Omni is today (`live (1).py`)

A single-file Gemini Live client, ~800 lines:

- **Audio**: PyAudio, `paInt16`, mono, **16 kHz send / 24 kHz receive**, `CHUNK_SIZE = 1024`
- **Video**: `--mode camera` (OpenCV `VideoCapture(0)`, BGR→RGB, thumbnail 1024², JPEG q85, **1 fps**) · `--mode screen` (`mss`, thumbnail 1920×1080, JPEG q80, 1 fps) · `--mode none`
- **Model**: `MODEL = "gemini-3.8-live-extended-thinking"` — **verify this string exists in the installed SDK's model list; it looks wrong and may be a typo/hallucination in the current file. Discover the correct live-model id and make it configurable via `GEMINI_LIVE_MODEL`.**
- **Config**: `LiveConnectConfig` with `response_modalities=["AUDIO"]`, `ThinkingConfig(thinking_level="high")`, `SpeechConfig` → `PrebuiltVoiceConfig(voice_name="Zephyr")`, input + output `AudioTranscriptionConfig`, `ContextWindowCompressionConfig(trigger_tokens=25600, sliding_window=SlidingWindow(target_tokens=12800))`
- **Concurrency**: `asyncio.TaskGroup` with tasks `send_text`, `send_realtime`, `listen_audio`, `capture_frames`|`capture_screen`, `receive_audio`, `play_audio`
- **Queues**: `out_queue` (mic+video → Gemini, `maxsize=5`, drop-oldest on full), `audio_in_queue` (Gemini audio → speaker, `maxsize=5`, drop-oldest)
- **Handling**: `server_content.interrupted` → drain `audio_in_queue`; `model_turn.parts[].inline_data` → audio; `input_transcription` → `You: …`; `output_transcription` → `Gemini: …`; `interaction_status` `IN_PROGRESS`/`IDLE`
- **Already-good defensive code**: `_select_input_device()` enumerates input-capable devices, prefers OS default, returns `(index, name, reason)` and never raises; `_diagnose_mic_error()` maps `-9999 Unanticipated host error` to the three real causes; every subsystem degrades gracefully with a printed explanation instead of crashing
- **Known defects to fix**: `============================================================` section banners are **not commented** (they're bare tokens — this file will not parse as Python; the uploaded copy has lost its `#` prefixes, verify against the real file); `if name == "main"` should be `__name__`/`__main__`; `TaskGroup` `ExceptionGroup` can still surface raw; `raise asyncio.CancelledError(...)` inside a `TaskGroup` body is not the correct cancellation pattern in 3.11+; no function-calling; no bridge; no overlay; console-only UI.

---

## 4. GAP ANALYSIS — WHAT MUST BE BUILT

### 4.1 Kratos side (brain + hands)

| # | Gap | Deliverable | Section |
|---|---|---|---|
| K1 | No `sovereign` approval mode; approval gate would block autonomous GUI/system work | 4th mode, new default, gate short-circuit, new capability tags | §6 |
| K2 | **Zero computer-control capability.** No keyboard, no mouse, no window management, no app launching, no UI perception | Entire **Computer Control Subsystem (CCS)**: `src/kratos_agent/ccs/` | §7–§12 |
| K3 | No screen perception inside Kratos (Omni's screen share is *Gemini's* eye, not Kratos's) | CCS Perception Engine: screenshot, OCR, a11y/UIA tree, element grounding, VLM fallback | §9 |
| K4 | No input injection | CCS Input Engine: platform-abstracted mouse/keyboard/touch, interlock, human-takeover detection | §10 |
| K5 | No window/app/system control | CCS System Engine: windows, processes, apps, services, registry, power, volume, network, scheduler, installers | §11 |
| K6 | No real browser driver (only `fetch_url` + DuckDuckGo search) | CCS Browser Engine: drive the user's actual browser via CDP + UIA + input injection | §12 |
| K7 | No elevation/admin path | CCS Elevation: self-elevating helper, `runas`, `osascript admin`, `sudo`/`pkexec`, integrity-level handling | §13.4 |
| K8 | No voice-facing API. `web/server.py` serves the React UI; its endpoints are UI-shaped | `/api/voice/*` REST + SSE surface, session mapping, cancel, steer, capability probe | §15 |
| K9 | Workspace-write confinement blocks system-wide file work | Path policy under `sovereign` + audit log | §13.6 |
| K10 | No emergency-stop server endpoint / global hotkey | `POST /api/voice/panic`, input interlock release, process-tree kill | §13.1 |
| K11 | No undo/rollback for machine mutations | Snapshot engine + `undo_last_operation` tool | §13.5 |
| K12 | Narration-shaped event stream doesn't exist | `AgentEvent` envelope, `voice_narratable` flag, speech-safe message field | §16 |
| K13 | Tool count/registry must grow from 24 → ~110 | `tools_list.json` schemas + `tools.py`/`ccs/` implementations + hot-reload wiring | §8 |
| K14 | Existing test suite must not break | Regression run before/after; new CCS + voice-API test modules | §34 |

### 4.2 Omni side (senses + voice + face)

| # | Gap | Deliverable | Section |
|---|---|---|---|
| O1 | No bridge to Kratos | `agent_bridge.py` — `KratosBridge` with health/submit/stream/cancel/status/steer/confirm | §19 |
| O2 | No intent routing; everything is just streamed to Gemini as chat | `intent_router.py` using **native Gemini Live function calling** (`function_declarations` in session config), with prompt-based classification fallback | §18 |
| O3 | No event normalization | `event_adapter.py` — SSE/JSON → `AgentEvent` | §16 |
| O4 | No voice-session state machine | `task_state.py` — `IDLE → LISTENING → ROUTING → EXECUTING → SPEAKING → COMPLETED/FAILED/CANCELLED` + `PANIC` | §21 |
| O5 | No narration layer | `narrator.py` — throttled event→speech, natural-language result summarization, no JSON, no CoT | §20 |
| O6 | No GUI at all (console only) | **Floating Jarvis overlay** — `overlay/`, `kratos-illu.png` avatar + mic/screen/camera buttons | §27 |
| O7 | Mic capture assumes 16 kHz device support | `audio.py` — enumerate, validate, capture at **native rate**, resample to 16 kHz (note: `audioop` is **removed in Python 3.13** — use `numpy`/`scipy.signal.resample_poly`) | §25 |
| O8 | Interruption handling drains queue but doesn't reset state | Full barge-in: flush, state reset, reclassify, cancel-stale-narration | §25.5 |
| O9 | `TaskGroup` `ExceptionGroup` can still reach the shell | Supervisor pattern that unwraps and prints real exceptions, per-domain isolation | §30 |
| O10 | Single file, ~800 lines, no modularity | Split into the module plan in §32 | §32 |
| O11 | No session↔Kratos-session mapping | `SessionRegistry` persisted to `.kratos/voice_sessions.json` | §23 |
| O12 | No mid-task steering ("actually, use PostgreSQL instead") | `POST /api/voice/task/{id}/message` + voice phrasing detection | §22 |
| O13 | Model string looks wrong; no SDK-version pinning discipline | Discovery + `GEMINI_LIVE_MODEL` env + graceful model-list fallback | §5, §29 |
| O14 | No screen/camera *selection* (which monitor, which camera) | Multi-monitor + multi-camera enumeration surfaced in the overlay | §26 |

---

## 5. PHASE 0 — MANDATORY DISCOVERY

**You MUST NOT write implementation code before this phase produces `DISCOVERY.md` at the workspace root.** It is also the raw material for the Final Report (§38).

For **every** row below, record one of:
- ✅ **Concrete finding** — `path/to/file.py:LINE` + the symbol/signature/route, quoted exactly.
- ⚠️ **DIVERGENCE** — README says X, code says Y. State which you follow and why.
- ❌ **NOT FOUND** — plus what you searched (`grep -rn` patterns used) and what you'll do instead.

### 5.1 Discovery matrix

| Area | Files to inspect | What to record |
|---|---|---|
| Omni entry | `live (1).py` / `live.py` and every import it resolves | Real model string, real config keys, real queue shapes, whether the section banners are commented |
| Omni deps | `pyproject.toml`, `requirements.txt`, `uv.lock`, `.venv/pyvenv.cfg`, `.python-version` | Exact interpreter version, exact `google-genai` version, exact `pyaudio`/`mss`/`opencv-python`/`pillow` versions |
| Gemini SDK surface | Installed `google-genai` — `types.LiveConnectConfig`, `types.Tool`, `types.FunctionDeclaration`, `types.Content`, `types.Part`, `types.FunctionCall`, `types.FunctionResponse`, `types.Blob`, `types.ThinkingConfig`, `types.SpeechConfig`, `types.AudioTranscriptionConfig`, `types.ContextWindowCompressionConfig`; `client.aio.live.connect`, `session.receive`, `session.send`, `session.send_client_content`, `session.send_realtime_input`, `session.close` | **Exact** parameter names and availability in the installed version. Which of these exist: function declarations in live config? `interrupted` flag path? realtime audio+video+text simultaneously? session resumption? `usage_metadata`? |
| Kratos runtime | `src/kratos_agent/main.py`, `__init__.py`, `__main__.py` | `KratosRuntime` real constructor signature, real public methods, package exports (`main`, `run_agent`, `runtime`, `set_model`, `reload_tools`) |
| Agent loop | `core/agent_loop.py` | Loop bound, how tool results re-enter the model, where events are emitted, how cancellation is checked |
| Planner | `core/planner.py` | Intent classes, plan item shape, state transitions, how a plan is (re)generated mid-task |
| Task manager | `core/task_manager.py` | Real state enum names and values, real event emission points, Rich rendering coupling (must not be required in headless/voice mode) |
| Event contracts | `core/runtime_contracts.py` | **Every field of `RuntimeEvent`**, **every member of `EventKind`**, serialization method |
| Event bus | `core/event_bus.py` | subscribe/publish signature, sync vs async, thread-safety, whether it can be tapped from a web handler |
| Event store | `core/event_store.py` | JSONL path, record shape, replay/resume support, whether it has an offset/cursor for `Last-Event-ID` |
| Background runner | `core/background_runner.py` | Task id shape, cancel method, status query, whether cancellation is exposed via HTTP or CLI-only |
| Memory | `core/memory.py`, `core/cognitive_memory.py` | Session creation API, session id format, persistence path, cross-session recall API |
| Verification | `core/verification_manager.py` | What it checks, result shape, how it reports pass/fail into events |
| Approval | `core/approval_mode.py` | Real mode enum, capability tags, **exact function(s) where the gate decision is made** — this is where `sovereign` short-circuits |
| Tool runtime | `core/tool_runtime.py` | Schema validation, permission check, time accounting, `ToolResult` shape, workspace-path confinement check location, **Wave Scheduler location + partition rules** |
| Tools | `utils/tools.py`, `utils/tools_list.json` | Real tool count, real names, real schema format, dispatch mechanism, how a forged tool gets registered |
| Tool forging | `utils/tool_creator.py`, `core/reloader.py` | Whether CCS tools can be added as forged tools or need first-class registration |
| Harness | `core/harness/{kernel,plugin,presets}.py`, `plugins/*` | Plugin base contract, preset definitions, service registration, event bus access from a plugin — **CCS SHOULD ship as a harness plugin** if the kernel supports it cleanly |
| Web server | `web/server.py` | **Every** `/api/*` route: path, method, request body, response body, auth. Every SSE endpoint. Exact SSE wire format (`event:`/`data:`/`id:`/`retry:`?). Completion + error events. Reconnect support. Bind address + port. Threading model. Static file serving. How it obtains the runtime instance |
| Reference client | `frontend/src/App.jsx` | **Ground truth for the wire format.** How it POSTs chat, how it reads SSE, how it parses events, how it detects completion/error, how it handles the agent passcode (`kratos`) |
| Provider runtime | `core/provider_runtime.py` | `ModelAdapter` contract, OmniRoute adapter, how multimodal parts (images) are passed to the model — **critical for CCS vision** |
| Subagents | `core/subagents.py` | Spawn signature, result shape, parallel fan-out limits, isolated history handling |
| Workspace tracker | `core/workspace_tracker.py` | What it tracks, how "files changed" is reported |
| D1 | `core/d1_client.py`, `core/d1_schema.sql` | Whether D1 is required or optional at runtime, local mirror fallback, exact columns of all 5 tables |
| Config/env | `.env`, `.env.example`, `brain/config.py` | Every env var actually read, defaults, which are required |
| Interpreters | Omni venv vs Kratos env | `python -V` in each. **This decides §14 process topology** |
| Cancellation | `background_runner.py`, `web/server.py`, `task_manager.py`, `agent_loop.py` | The real mechanism. README's `/bg-cancel <id>` — is it wired to HTTP, CLI-only, or absent? |
| Sessions | `memory.py`, `web/server.py`, `frontend/src/App.jsx` | How a session id is minted, stored, reused |
| Existing tests | `tests/*` | Enumerate every file, count tests, **run the full suite and record the baseline result** |
| Assets | `kratos_banner.png`, `kratos_badge.png`, `docs/kratos_web_ui.png`, `frontend/public/**` | **Does `kratos-illu.png` exist? Where? What are its dimensions, transparency, and aspect ratio?** If absent, record that and ask — do not silently substitute the banner |
| OS | host platform | Windows build / macOS version / distro + X11 vs Wayland. **CCS is platform-specific; you must know which platform you are targeting and implement that one first-class, with the others as documented stubs that raise `CapabilityUnavailable`.** |
| Installed system tools | `xdotool`, `ydotool`, `wmctrl`, `xclip`, `tesseract`, `winget`, `choco`, `scoop`, `brew`, `adb` | Which exist; CCS uses what's there and self-installs what's missing under `sovereign` |

### 5.2 Discovery output format

```markdown
# DISCOVERY.md

## 0. Environment
- Host OS: Windows 11 Pro 23H2 (build 22631)   # or: macOS 15.2 / Ubuntu 24.04 + X11
- Omni interpreter: /…/omni/.venv/bin/python → 3.13.1
- Kratos interpreter: uv-managed → 3.14.0
- google-genai: 1.x.y
- pyaudio: 0.2.14 | mss: 9.0.1 | opencv-python: 4.x | pillow: 10.x
- Kratos test baseline: 20 modules / 130 tests — 128 passed, 2 skipped, 0 failed
- kratos-illu.png: FOUND at ./kratos-illu.png, 1024×1024, RGBA
  (or) NOT FOUND — searched `find . -iname '*illu*'`, `ls`, `frontend/public`. Blocker: §27.

## 1. Web API (ground truth from web/server.py + App.jsx)
| Route | Method | Request | Response | Source |
|---|---|---|---|---|
| /api/chat | POST | {…} | {…} | web/server.py:214 |
…
### SSE wire format (verbatim sample)
```
…
```

## 2. RuntimeEvent / EventKind (verbatim)
```python
class EventKind(str, Enum): …
@dataclass class RuntimeEvent: …
```

## 3. Approval gate — exact decision point
`core/approval_mode.py:88` — `def resolve(self, capability, target) -> Decision` …

## N. Divergences
| # | README claim | Actual code | Following | Why |
…

## N+1. Blockers
…
```

**If Phase 0 surfaces a load-bearing blocker (e.g. Kratos has no SSE endpoint at all, or `kratos-illu.png` doesn't exist), record it, propose the minimal resolution, and continue with everything that isn't blocked. Do not stall the whole build on one unknown.**

---

## 6. KRATOS CHANGE 1 — SOVEREIGN MODE

### 6.1 Extend the approval mode enum

Locate the real enum in `core/approval_mode.py` (Phase 0 §5.1). Add `SOVEREIGN`.

```python
class ApprovalMode(str, Enum):
    SUGGEST   = "suggest"
    AUTO_EDIT = "auto-edit"
    FULL_AUTO = "full-auto"
    SOVEREIGN = "sovereign"      # NEW — default for Jarvis
```

### 6.2 Extend capability tags

Existing: `read`, `write`, `execute`, `git`, `network`. Add:

| Tag | Covers |
|---|---|
| `input` | keyboard/mouse/touch injection |
| `display` | screen capture, window manipulation, monitor config |
| `gui` | a11y/UIA tree access, element interaction, app-level GUI operations |
| `system` | power, services, scheduled tasks, startup, env vars, hosts file |
| `admin` | anything requiring elevation |
| `registry` | Windows registry / macOS plist / dconf-gsettings |
| `install` | package managers, installers, `pip`/`npm`/`uv` mutations |
| `destructive` | delete, format, `rm -rf`, service removal, shutdown/restart |
| `browser` | real browser driving incl. authenticated sessions |
| `persist` | anything that outlives the process (cron, service, startup entry, watcher) |

Every new CCS tool (§8) declares its tags. Under `sovereign`, **all tags resolve to allow**.

### 6.3 Gate short-circuit

At the exact decision function found in Phase 0:

```python
def resolve(self, capability: str, target: str | None = None) -> Decision:
    if self.mode is ApprovalMode.SOVEREIGN:
        # Jarvis authority. No human in the loop. Audit only.
        self._audit.record(capability=capability, target=target, decision="ALLOW", mode="sovereign")
        return Decision(allow=True, needs_confirmation=False, reason="sovereign")
    # … existing behaviour for the other three modes, unchanged …
```

**MUST NOT** delete or weaken the other three modes — they stay functional for users who select them via `/mode`, `KRATOS_APPROVAL_MODE`, or `POST /api/voice/approval_mode`.

### 6.4 Workspace confinement lift

Locate the path-confinement check (likely `core/tool_runtime.py` — Phase 0). Under `sovereign`:

- The check becomes an **audit record**, not a denial.
- Write the absolute resolved path, the tool, the byte size, and a SHA-256 of the pre-image (for undo, §13.5) to `AuditTrail`.
- Still resolve symlinks and `..` before acting — not for safety, for **correctness** (you want the audit log to name the real file).

Under any other mode, confinement stays exactly as it is today.

### 6.5 Default flip

- `KRATOS_APPROVAL_MODE` default: `full-auto` → **`sovereign`**.
- Update `.env.example` with `KRATOS_APPROVAL_MODE=sovereign` and a one-line comment.
- Update `web/server.py`'s reported mode, `tui/status_bar.py`'s display, and `frontend` mode indicator if present.
- `/mode sovereign` becomes a valid CLI slash command; `/mode` with no arg lists all four.
- Status bar shows `⚡ SOVEREIGN` in the accent color.

### 6.6 Capability probe

New: `KratosRuntime.probe_capabilities() -> dict` — runs once at startup (and on demand via `/api/voice/capabilities`) and reports what this machine can actually do right now:

```json
{
  "platform": "windows", "os_build": "22631", "arch": "amd64",
  "user": "THIRU\\dev", "is_admin_session": false, "can_elevate": true,
  "elevation_method": "shell_execute_runas",
  "displays": [{"id": 0, "name": "\\\\.\\DISPLAY1", "w": 2560, "h": 1440, "scale": 1.5, "primary": true}],
  "input": {"keyboard": true, "mouse": true, "touch": false, "injection_method": "sendinput"},
  "input_can_reach_elevated_windows": false,
  "perception": {"screenshot": true, "ocr": "rapidocr", "a11y": "uia", "vlm_grounding": true},
  "browsers": [{"name": "chrome", "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "cdp": true, "profiles": ["Default","Profile 1"]}],
  "package_managers": ["winget", "choco", "scoop", "pip", "uv", "npm"],
  "shell": "powershell.exe",
  "ccs_tools_registered": 87,
  "missing": ["touch input", "elevated-window input injection (needs helper)"],
  "voice_api": {"enabled": true, "port": 7860, "bind": "127.0.0.1"}
}
```

Omni reads this at startup and speaks it once on request (`"Jarvis, what can you do?"`) — the answer is generated from this payload, never hardcoded.

---

## 7. KRATOS CHANGE 2 — COMPUTER CONTROL SUBSYSTEM (CCS)

### 7.1 Location & shape

```
src/kratos_agent/ccs/
├── __init__.py                 # public exports: CCS, get_ccs, CapabilityUnavailable
├── base.py                     # PlatformBackend ABC, CapabilityUnavailable, ActionResult, ElementHandle, Rect, Point
├── registry.py                 # backend discovery + selection + capability negotiation
├── perception/
│   ├── __init__.py
│   ├── screenshot.py           # mss-based multi-monitor capture, region crop, DPI-normalize, cursor overlay
│   ├── ocr.py                  # rapidocr-onnxruntime primary, pytesseract fallback, cached per-region
│   ├── a11y_windows.py         # IUIAutomation via comtypes — tree walk, patterns, bounding rects
│   ├── a11y_macos.py           # AXUIElement via pyobjc ApplicationServices
│   ├── a11y_linux.py           # AT-SPI2 via pyatspi / dogtail
│   ├── grounding.py            # element resolution: a11y → OCR → template match → VLM coordinate grounding
│   ├── diff.py                 # before/after frame diff to confirm an action landed
│   └── templates.py            # cv2.matchTemplate icon library under .kratos/ccs/templates/
├── input/
│   ├── __init__.py
│   ├── interlock.py            # THE critical piece: human-vs-agent input arbitration (§10.4)
│   ├── windows.py              # SendInput via ctypes, scan codes, absolute mouse coords, UIPI helper client
│   ├── macos.py                # Quartz CGEvent via pyobjc
│   ├── linux.py                # xdotool / ydotool / uinput
│   └── keys.py                 # cross-platform key-name → platform-code map ("ctrl+shift+esc", "cmd+space", "alt+f4", "media_play_pause", "f13"…"f24")
├── windows/                    # OS window management (not "Windows the OS" — window objects)
│   ├── __init__.py
│   ├── manager.py              # list/focus/move/resize/min/max/restore/close/screenshot per window
│   ├── desktop.py              # virtual desktops, work areas, monitor topology, DPI awareness
│   └── alwaysontop.py          # pin/unpin window topmost
├── apps/
│   ├── __init__.py
│   ├── launcher.py             # start by name/path/protocol/shell-verb, elevated or not, with args + cwd + env
│   ├── process.py              # enumerate (psutil), kill tree, wait, resource sample
│   ├── installer.py            # winget/choco/scoop/brew/apt/dnf/pacman detection + install + verify
│   ├── terminal.py             # drive a REAL terminal window (Windows Terminal / iTerm / gnome-terminal) with capture via UIA/conpty
│   └── adapters/               # high-level per-app skills, each optional and lazy-loaded
│       ├── base.py             # AppAdapter ABC: name(), detect(), capabilities()
│       ├── chrome.py  edge.py  firefox.py       # via CDP + UIA
│       ├── vscodium.py  cursor.py  antigravity.py  pycharm.py
│       ├── explorer.py  finder.py  nautilus.py
│       ├── office.py  libreoffice.py
│       ├── spotify.py  vlc.py
│       ├── discord.py  slack.py  teams.py  whatsapp.py  telegram.py
│       ├── settings.py                        # OS settings deep links (ms-settings:, x-apple.systempreferences:)
│       └── registry_editor.py  task_manager.py  device_manager.py
├── browser/
│   ├── __init__.py
│   ├── cdp.py                  # attach to a real running Chrome/Edge over --remote-debugging-port
│   ├── driver.py               # navigate/click/type/read/js/download/cookies/tabs — all through CDP when available
│   ├── fallback.py             # no CDP → pure UIA + input injection + OCR (works on any browser, any page)
│   └── profiles.py             # use the user's real profile so logged-in sessions are available
├── system/
│   ├── __init__.py
│   ├── elevation.py            # §13.4
│   ├── power.py                # lock/sleep/shutdown/restart/logoff/monitor-off
│   ├── services.py             # SCM / launchctl / systemctl
│   ├── scheduler.py            # Task Scheduler / launchd / cron — persistent autonomy
│   ├── registry.py             # winreg / plistlib / gsettings-dconf
│   ├── env.py                  # user + machine env vars, PATH mutation
│   ├── network.py              # interfaces, wifi scan/connect, bluetooth, hosts file, firewall
│   ├── audio.py                # volume, mute, default device, media transport keys
│   ├── notifications.py        # read/raise/dismiss OS notifications
│   ├── clipboard.py            # text, image, files, formats
│   └── fs_extra.py             # open-with-default-app, reveal-in-explorer, shortcuts, file associations
├── safety_ops.py               # panic, interlock release, snapshot, undo, audit (§13)
└── plugin.py                   # CCSHarnessPlugin — registers the CCS service into HarnessKernel
```

### 7.2 Backend abstraction

```python
# ccs/base.py
class CapabilityUnavailable(RuntimeError):
    """Raised when a requested capability is not present on this platform/machine.
    Carries enough info for the model to work around it or self-install what's missing."""
    def __init__(self, capability: str, platform: str, hint: str = "", install: str | None = None):
        self.capability, self.platform, self.hint, self.install = capability, platform, hint, install
        super().__init__(f"{capability} unavailable on {platform}. {hint}" + (f" Install with: {install}" if install else ""))

@dataclass(frozen=True)
class Point:   x: int; y: int
@dataclass(frozen=True)
class Rect:    x: int; y: int; w: int; h: int
    @property
    def center(self) -> Point: ...

@dataclass
class ElementHandle:
    """A resolved UI element. Opaque `native` payload is platform-specific (UIA IUIAutomationElement, AXUIElementRef, AT-SPI Accessible)."""
    ref: str                       # stable short id for the model to reference ("e17")
    role: str                      # "Button", "Edit", "ListItem", "MenuItem", …
    name: str                      # accessible name / label
    value: str | None
    rect: Rect
    states: list[str]              # ["focused", "enabled", "checked", "expanded"]
    patterns: list[str]            # ["Invoke", "Value", "Toggle", "SelectionItem", "Scroll"]
    app: str                       # process name
    window: str                    # window title
    depth: int
    native: object | None = None
    def to_model_dict(self) -> dict: ...   # compact, Headroom-friendly

@dataclass
class ActionResult:
    ok: bool
    action: str
    detail: str = ""
    data: dict | None = None
    screenshot_ref: str | None = None      # id of the post-action frame, if captured
    duration_ms: int = 0

class PlatformBackend(ABC):
    platform: str = "abstract"

    # perception
    @abstractmethod
    def screenshot(self, monitor: int | None = None, region: Rect | None = None,
                   include_cursor: bool = False) -> bytes: ...   # PNG bytes
    @abstractmethod
    def a11y_supported(self) -> bool: ...
    @abstractmethod
    def dump_tree(self, app: str | None = None, root_window: str | None = None,
                  max_depth: int = 12, max_nodes: int = 800,
                  visible_only: bool = True) -> list[ElementHandle]: ...
    @abstractmethod
    def find_element(self, query: str, app: str | None = None,
                     role: str | None = None, index: int = 0) -> ElementHandle | None: ...

    # input
    @abstractmethod
    def mouse_move(self, p: Point, duration_ms: int = 0) -> ActionResult: ...
    @abstractmethod
    def mouse_click(self, p: Point | None = None, button: str = "left",
                    clicks: int = 1, modifiers: list[str] = ()) -> ActionResult: ...
    @abstractmethod
    def mouse_drag(self, a: Point, b: Point, button: str = "left",
                   duration_ms: int = 200, steps: int = 24) -> ActionResult: ...
    @abstractmethod
    def mouse_scroll(self, dy: int, dx: int = 0, at: Point | None = None) -> ActionResult: ...
    @abstractmethod
    def key_tap(self, keys: list[str]) -> ActionResult: ...
    @abstractmethod
    def type_text(self, text: str, interval_ms: int = 0,
                  strategy: str = "auto") -> ActionResult: ...   # auto|event|clipboard

    # windows
    @abstractmethod
    def list_windows(self, include_minimized: bool = True) -> list[dict]: ...
    @abstractmethod
    def focus_window(self, handle: str | int | None = None, title_regex: str | None = None) -> ActionResult: ...
    @abstractmethod
    def window_action(self, handle, action: str, rect: Rect | None = None) -> ActionResult: ...

    # system
    @abstractmethod
    def launch(self, target: str, args: list[str] = (), cwd: str | None = None,
               elevated: bool = False, verb: str | None = None,
               wait: bool = False, timeout: float | None = None) -> ActionResult: ...
    @abstractmethod
    def can_elevate(self) -> bool: ...
    @abstractmethod
    def run_elevated(self, command: str, wait: bool = True,
                     timeout: float | None = None) -> ActionResult: ...
    @abstractmethod
    def display_info(self) -> list[dict]: ...
```

`ccs/registry.py` picks the backend by `sys.platform`, verifies each capability at import time (cheap probes only — no window opens), and populates the capability table used by `probe_capabilities()` (§6.6). Any unimplemented method raises `CapabilityUnavailable` **with an install hint**, so the model can respond by calling `system_install_package` and retrying — that's the self-extending loop that removes the last limitations.

### 7.3 Harness integration

CCS ships as **`CCSHarnessPlugin`** (`ccs/plugin.py`), registered in `core/harness/presets.py`:

- Add `ccs` to the `full` preset; add a **new `jarvis` preset** = `full` + `ccs` + `voice` plugins, and make `jarvis` the default preset when `KRATOS_APPROVAL_MODE=sovereign`.
- On `start()`: register the shared `"ccs"` service in `HarnessKernel`, subscribe to the kernel event bus, register all CCS tool schemas into the tool registry via the existing tools-plugin path, publish `ccs:ready`.
- On `stop()`: release the input interlock (§10.4), stop the elevated helper if we spawned it, close CDP sockets, publish `ccs:stopped`.
- MUST NOT crash kernel startup if a CCS dependency is missing — degrade, publish `ccs:degraded` with the missing list, and let the rest of Kratos run.

### 7.4 Multimodal results

Perception tools return **images**. Verify in Phase 0 how `core/provider_runtime.py` / `brain/chat_model.py` pass image parts to the gateway. Requirements:

- `screenshot_capture` returns a `ToolResult` whose payload includes an **image part** (`{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}` or the gateway's equivalent) *and* a text summary line so the Wave Scheduler / Headroom can still reason about it.
- Downscale to ≤ 1568 px on the long edge, JPEG q78, before sending. Keep the full-res PNG on disk under `.kratos/ccs/frames/` and reference it by id.
- Headroom MUST NOT try to compress base64 image blobs. Add a content-type guard in `context_pipeline.py` (`image/*` → skip compression, apply resolution reduction instead).
- If the active model has no vision, `screenshot_capture` falls back to OCR + a11y text and says so explicitly in the tool result.

---

## 8. CCS TOOL CATALOG

Add every tool below to `utils/tools_list.json` (real schema format from Phase 0) with implementations delegating into `ccs/`. Capability tags in the last column.

**Total registry grows from 24 → ~115 tools.**

### 8.1 Perception (Kratos's own eyes)

| Tool | Params | Returns | Tags |
|---|---|---|---|
| `screenshot_capture` | `monitor?:int, region?:{x,y,w,h}, include_cursor?:bool, downscale?:int` | image part + `{path, w, h, monitor}` | `read`,`display` |
| `screen_read_text` | `region?, monitor?, lang?:str, dedupe?:bool` | OCR text + per-line boxes | `read`,`display` |
| `ui_tree_dump` | `app?:str, window?:str, max_depth?:int=12, max_nodes?:int=800, visible_only?:bool=true, roles?:[str]` | compressed `ElementHandle[]` (Headroom-JSON) | `read`,`gui` |
| `ui_find` | `query:str, app?:str, role?:str, index?:int=0, near?:{x,y}` | single `ElementHandle` + ref id | `read`,`gui` |
| `ui_find_all` | `query:str, app?:str, role?:str, limit?:int=25` | `ElementHandle[]` | `read`,`gui` |
| `ui_read_element` | `ref:str` | full attributes + current value + available patterns | `read`,`gui` |
| `ui_invoke` | `ref:str, pattern?:str="Invoke", value?:str` | `ActionResult` — direct a11y invocation, no clicking needed | `gui` |
| `screen_wait_for` | `expectation:str, mode?:"text"\|"element"\|"visual"\|"gone", timeout?:float=20, poll?:float=0.4, region?` | `{found:bool, matched:str, elapsed_ms}` | `read`,`display`,`gui` |
| `screen_diff` | `ref_a?:str, ref_b?:str, threshold?:float` | changed-region rects + summary | `read`,`display` |
| `active_window_info` | — | title, app, pid, rect, focused element | `read`,`gui` |
| `display_info` | — | monitors, resolution, scale, DPI, arrangement | `read`,`display` |
| `cursor_position` | — | `{x,y}`, monitor, element under cursor | `read`,`input` |
| `read_notifications` | `app?:str, limit?:int=20, since?:str` | OS notification list | `read`,`system` |
| `clipboard_get` | `format?:str="auto"` | text / image ref / file list | `read`,`system` |

### 8.2 Input injection (Kratos's hands)

| Tool | Params | Returns | Tags |
|---|---|---|---|
| `mouse_move` | `x:int, y:int, duration_ms?:int=0, smooth?:bool=true` | `ActionResult` | `input` |
| `mouse_click` | `x?:int, y?:int, ref?:str, button?:"left"\|"right"\|"middle"\|"x1"\|"x2", clicks?:int=1, modifiers?:[str], hold_ms?:int=0` | `ActionResult` + optional post-shot | `input`,`gui` |
| `mouse_double_click` | `x?,y?,ref?` | `ActionResult` | `input`,`gui` |
| `mouse_right_click` | `x?,y?,ref?` | `ActionResult` | `input`,`gui` |
| `mouse_drag` | `from:{x,y}\|ref, to:{x,y}\|ref, button?:str="left", duration_ms?:int=200` | `ActionResult` | `input`,`gui` |
| `mouse_scroll` | `dy:int, dx?:int=0, at?:{x,y}, ref?:str, smooth?:bool` | `ActionResult` | `input`,`gui` |
| `key_tap` | `keys:str` ("ctrl+shift+esc", "cmd+space", "alt+f4", "enter", "media_play_pause") | `ActionResult` | `input` |
| `type_text` | `text:str, interval_ms?:int=0, strategy?:"auto"\|"event"\|"clipboard", clear_first?:bool` | `ActionResult` — clipboard strategy for unicode/long text; restores prior clipboard | `input` |
| `key_hold` | `key:str, ms:int` | `ActionResult` | `input` |
| `input_sequence` | `actions:[{type,...}]` | batched atomic macro, single interlock acquisition, per-step results | `input`,`gui` |
| `input_lock_state` | — | caps/num/scroll lock, stuck-modifier detection | `read`,`input` |
| `input_release_all` | — | force-release every held key/button; recover from a stuck modifier | `input` |
| `record_macro` | `name:str, seconds?:float, until?:str` | saved to `.kratos/ccs/macros/{name}.json` | `input`,`persist` |
| `play_macro` | `name:str, speed?:float=1.0, loop?:int=1` | `ActionResult` | `input`,`persist` |

### 8.3 Window & desktop

| Tool | Params | Tags |
|---|---|---|
| `window_list` | `include_minimized?:bool=true, app?:str` | `read`,`display` |
| `window_focus` | `handle?:str, title_regex?:str, app?:str, create_if_missing?:bool` | `display`,`gui` |
| `window_action` | `handle:str, action:"minimize"\|"maximize"\|"restore"\|"close"\|"force_close"\|"pin_top"\|"unpin_top"\|"hide"` | `display`,`gui` |
| `window_move_resize` | `handle:str, x,y,w,h, monitor?:int` | `display` |
| `window_screenshot` | `handle:str, client_only?:bool=true` | `read`,`display` |
| `window_arrange` | `layout:"tile_h"\|"tile_v"\|"cascade"\|"grid"\|"stack", handles?:[str]` | `display` |
| `virtual_desktop` | `action:"list"\|"new"\|"switch"\|"close"\|"move_window", index?:int, handle?:str` | `display`,`system` |
| `wallpaper_set` | `path:str\|url:str, monitor?:int` | `system`,`network` |

### 8.4 Applications & processes

| Tool | Params | Tags |
|---|---|---|
| `app_launch` | `target:str, args?:[str], cwd?:str, elevated?:bool=false, verb?:str, wait?:bool=false, timeout?:float, env?:{}` — target may be exe path, app name, shell: URI, `ms-settings:` page, protocol handler, or a document path (opens with default app) | `execute`,`system`,`admin?` |
| `app_list_running` | `filter?:str, include_system?:bool=false` | `read`,`system` |
| `app_terminate` | `pid?:int, name?:str, tree?:bool=true, force?:bool=false, graceful_timeout?:float=5` | `execute`,`system`,`destructive` |
| `app_wait` | `pid?:int, name?:str, window_title?:str, state?:"running"\|"exited"\|"idle", timeout?:float=30` | `read`,`system` |
| `app_install` | `package:str, manager?:"auto"\|"winget"\|"choco"\|"scoop"\|"brew"\|"apt"\|"dnf"\|"pacman"\|"pip"\|"uv"\|"npm", elevated?:bool=true, verify?:bool=true, args?:[str]` | `install`,`system`,`admin`,`network` |
| `app_uninstall` | `package:str, manager?:str` | `install`,`system`,`admin`,`destructive` |
| `app_search_store` | `query:str, source?:"winget"\|"choco"\|"brew"\|"apt"` | `read`,`network` |
| `app_switch` | `direction?:"next"\|"prev", name?:str` | `gui`,`display` |
| `app_command_palette` | `app?:str` — opens Ctrl+Shift+P / Cmd+Shift+P / Alt+Space depending on target | `gui` |
| `process_list` | `filter?:str, sort?:"cpu"\|"mem", limit?:int=50` | `read`,`system` |
| `process_kill` | `pid:int, tree?:bool=true` | `execute`,`system`,`destructive` |
| `process_resources` | `pid?:int, sample_seconds?:float=2` | `read`,`system` |

### 8.5 Real terminal (a visible one, not just `subprocess`)

| Tool | Params | Tags |
|---|---|---|
| `terminal_open` | `shell?:"auto"\|"pwsh"\|"powershell"\|"cmd"\|"bash"\|"zsh", cwd?:str, elevated?:bool=false, title?:str` → `{session_id}` | `execute`,`display` |
| `terminal_send` | `session_id:str, command:str, enter?:bool=true` | `execute` |
| `terminal_read` | `session_id:str, lines?:int=200, since?:str, via?:"uia"\|"conpty"\|"screenshot_ocr"` | `read`,`execute` |
| `terminal_wait_for_prompt` | `session_id:str, timeout?:float=60, idle_ms?:int=600` | `read`,`execute` |
| `terminal_close` | `session_id:str, force?:bool=false` | `execute`,`destructive` |

*Why:* `run_terminal_command` (existing) uses `subprocess` — great for headless work and stays the default. `terminal_*` exists for when the task genuinely needs a **visible** shell (interactive CLIs, TUIs, things that must survive Kratos, things the user wants to watch). Under `sovereign` the model picks.

### 8.6 System, admin, persistence

| Tool | Params | Tags |
|---|---|---|
| `system_info` | — | `read`,`system` |
| `system_elevate` | `command:str, wait?:bool=true, timeout?:float, capture?:bool=true` | `execute`,`system`,`admin` |
| `system_power` | `action:"lock"\|"sleep"\|"hibernate"\|"shutdown"\|"restart"\|"logoff"\|"monitor_off"\|"cancel_shutdown", delay_s?:int=0, force?:bool=false` | `system`,`admin`,`destructive` |
| `service_control` | `name:str, action:"status"\|"start"\|"stop"\|"restart"\|"enable"\|"disable"\|"install"\|"remove"` | `system`,`admin`,`destructive?` |
| `registry_read` | `hive:str, key:str, value?:str` | `read`,`registry` |
| `registry_write` | `hive:str, key:str, value:str, data:str, type?:"REG_SZ"\|"REG_DWORD"\|"REG_BINARY"\|"REG_MULTI_SZ", backup?:bool=true` | `registry`,`system`,`admin`,`destructive` |
| `registry_delete` | `hive:str, key:str, value?:str, backup?:bool=true` | `registry`,`system`,`admin`,`destructive` |
| `env_var` | `action:"get"\|"set"\|"delete"\|"list", name?:str, value?:str, scope?:"process"\|"user"\|"machine"` | `system`,`admin?` |
| `schedule_task` | `action:"create"\|"list"\|"run"\|"delete", name?:str, command?:str, trigger?:{type:"at"\|"daily"\|"weekly"\|"on_logon"\|"on_event"\|"interval", …}` | `system`,`admin`,`persist` |
| `startup_entry` | `action:"add"\|"remove"\|"list", name?:str, command?:str` | `system`,`admin`,`persist` |
| `file_open` | `path:str, app?:str, elevated?:bool=false` | `execute`,`system` |
| `file_reveal` | `path:str, select?:bool=true` | `display`,`system` |
| `file_delete` | `path:str, permanent?:bool=false, snapshot?:bool=true` | `destructive` |
| `file_move` / `file_copy` | `src, dst, overwrite?:bool, snapshot?:bool` | `write`,`destructive?` |
| `shortcut_create` | `path:str, target:str, args?:str, icon?:str, hotkey?:str, run_as_admin?:bool` | `write`,`system`,`persist` |
| `volume_control` | `action:"set"\|"up"\|"down"\|"mute"\|"unmute"\|"get", value?:int, device?:str` | `system` |
| `media_control` | `action:"play_pause"\|"next"\|"prev"\|"stop"\|"get_status"` | `system`,`gui` |
| `network_info` | — | `read`,`network`,`system` |
| `wifi_control` | `action:"scan"\|"connect"\|"disconnect"\|"list_profiles", ssid?:str, key?:str` | `network`,`system`,`admin` |
| `bluetooth_control` | `action:"on"\|"off"\|"scan"\|"pair"\|"unpair", device?:str` | `system`,`admin` |
| `hosts_file_edit` | `action:"add"\|"remove"\|"list", hostname?:str, ip?:str, backup?:bool=true` | `system`,`admin`,`destructive` |
| `firewall_rule` | `action:"add"\|"remove"\|"list", …` | `system`,`admin`,`destructive` |
| `clipboard_set` | `content:str\|{image_ref}\|{files:[...]}, format?:str` | `system` |
| `disk_info` / `disk_cleanup` | `path?:str` / `targets?:[str], dry_run?:bool=false` | `read` / `system`,`destructive` |

### 8.7 Browser (real, authenticated)

| Tool | Params | Tags |
|---|---|---|
| `browser_open` | `url:str, browser?:"auto"\|"chrome"\|"edge"\|"firefox"\|"brave", profile?:str, new_window?:bool=false, incognito?:bool=false` | `browser`,`network` |
| `browser_navigate` | `action:"back"\|"forward"\|"reload"\|"home"\|"goto", url?:str` | `browser` |
| `browser_tab` | `action:"list"\|"new"\|"switch"\|"close"\|"move", index?:int, url?:str` | `browser` |
| `browser_click` | `selector?:str, text?:str, ref?:str, x?:int, y?:int, button?:str, modifiers?:[str]` | `browser`,`input` |
| `browser_type` | `selector?\|ref?, text:str, clear?:bool=true, submit?:bool=false` | `browser`,`input` |
| `browser_read` | `mode:"text"\|"html"\|"markdown"\|"a11y"\|"screenshot"\|"links"\|"tables", selector?:str, max_chars?:int=40000` | `browser`,`read` |
| `browser_js` | `script:str, frame?:str, await_promise?:bool=true` | `browser`,`execute` |
| `browser_snapshot_dom` | — → serialized a11y snapshot with stable node ids for precise interaction | `browser`,`read` |
| `browser_fill_form` | `fields:[{selector\|label\|ref, value, type?}]` | `browser`,`input` |
| `browser_download` | `url?:str, wait?:bool=true, dest?:str, timeout?:float=120` | `browser`,`network`,`write` |
| `browser_wait_for` | `condition:str, mode:"text"\|"url"\|"selector"\|"gone"\|"load", timeout?:float=20` | `browser`,`read` |
| `browser_profile_list` | `browser?:str` | `browser`,`read` |
| `browser_state` | — → url, title, tabs, focused element, dialog present? | `browser`,`read` |
| `browser_dialog` | `action:"accept"\|"dismiss"\|"type", text?:str` | `browser`,`gui` |
| `browser_screenshot` | `full_page?:bool=false, selector?:str` | `browser`,`read`,`display` |

**MUST**: `browser_*` uses **CDP against a real browser started with the user's real profile** so existing logins work. If CDP is unavailable, fall back to UIA + input injection + OCR (`browser/fallback.py`). Never silently downgrade to headless — the user should be able to *see* Jarvis driving.

### 8.8 High-level delegated GUI autonomy

| Tool | Params | Tags |
|---|---|---|
| `computer_task` | `goal:str, max_steps?:int=40, perceive_every_step?:bool=true, allowed_apps?:[str], stop_on?:[str], narrate?:bool=true, budget_seconds?:float=600` → runs its own perceive→plan→act→verify loop, streaming `AgentEvent`s the whole way | `gui`,`input`,`display`,`execute`,`browser`,`system` |
| `app_task` | `app:str, goal:str, max_steps?:int=25` — same loop scoped to one application via its adapter | `gui`,`input` |
| `verify_gui_state` | `expectation:str, evidence?:"screenshot"\|"a11y"\|"text"\|"all"` → `{met:bool, evidence_ref, discrepancy}` | `read`,`gui` |
| `gui_explore` | `app?:str, depth?:int=3` — walk menus/tabs/dialogs and build a capability map of an unfamiliar app, cached to `.kratos/ccs/appmaps/` | `read`,`gui` |
| `self_install_capability` | `capability:str` — maps a `CapabilityUnavailable` to the right package manager and installs it, then hot-reloads the CCS backend | `install`,`system`,`admin`,`network` |

`computer_task` is the workhorse for *"open Chrome and apply to those jobs"*. It MUST:
- capture a screenshot **before and after** each action and diff them to confirm the action landed;
- on no-change-after-action, retry once with a different strategy (a11y invoke → real click → coordinate click → keyboard equivalent);
- after 3 consecutive failures on the same step, surface a `FAILED` event with the last frame ref rather than looping to `max_steps`;
- emit one narration-worthy event per **meaningful milestone**, not per micro-step (§16.4);
- respect the interlock (§10.4) and the panic stop (§13.1).

---

## 9. CCS PERCEPTION ENGINE

### 9.1 Screenshot

- Use **`mss`** with the lowercase factory: `from mss import mss; with mss() as sct: ...`. (The old `mss.MSS()` capitalization is wrong for current versions. Verify against the pinned version — Phase 0.)
- `sct.monitors[0]` = all monitors composited; `[1]` = primary; `[2..]` = secondaries. Expose monitor selection.
- **Windows DPI**: the process MUST declare DPI awareness (`ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)` = Per-Monitor V2, falling back to `SetProcessDpiAwareness(2)`, falling back to `shcore`/`user32` variants) **before** any capture, or screenshots come back scaled and every coordinate is wrong. Do this once at CCS init and record which call succeeded.
- Convert BGRA → RGB via `numpy`, then `PIL.Image.frombytes`.
- Cache frames to `.kratos/ccs/frames/{ts}_{id}.png`, keep a bounded ring (default last 200 frames, configurable), and return a stable `frame_ref` id the model can refer back to (`screen_diff ref_a="f17"`).
- Optional cursor rendering (`include_cursor`) — draw the real cursor position as a small marker so the model can reason about pointer state.

### 9.2 OCR

- **Primary: `rapidocr-onnxruntime`** — offline, ONNX, no system binary, good multilingual accuracy, fast enough for interactive loops.
- **Fallback: `pytesseract`** if a `tesseract` binary is present.
- Under `sovereign`, if neither is available, call `app_install` to get one and retry (this is the self-extension loop).
- Return both the plain text **and** line-level boxes `[{text, x, y, w, h, conf}]` so `grounding.py` can turn "the blue Submit button" into coordinates.
- Dedupe repeated lines (log tails, tables) before handing to the model — feed through Headroom's log engine.

### 9.3 Accessibility / UI Automation tree — **the primary perception channel**

Vision alone is slow and imprecise. **a11y trees are the correct primary source.** Always prefer them.

**Windows — IUIAutomation (`comtypes` + `UIAutomationClient.dll`):**
- `CoCreateInstance(CUIAutomation8)` → `IUIAutomation`.
- `GetRootElement()`, then `CreateTreeWalker` with a `CacheRequest` (fetch `Name`, `ControlType`, `AutomationId`, `ClassName`, `BoundingRectangle`, `IsEnabled`, `IsOffscreen`, `ValueValue`, `HasKeyboardFocus` in one pass — **caching is essential**; uncached walks of a big app take seconds).
- Patterns to query: `Invoke`, `Toggle`, `Value`, `RangeValue`, `SelectionItem`, `Selection`, `ExpandCollapse`, `Scroll`, `ScrollItem`, `Grid`, `GridItem`, `Text`, `Window`, `Transform`, `LegacyIAccessible`.
- Filter `IsOffscreen == True` by default; keep them on request (`visible_only=false`).
- Handle cross-process COM correctly: initialize `CoInitializeEx(COINIT_MULTITHREADED)` on the worker thread, and **pin all UIA work to one dedicated thread** — UIA COM objects are apartment-sensitive and calling them from arbitrary asyncio threads produces intermittent `RPC_E_WRONG_THREAD` / `0x80040201`. This is a real bug class; design around it (§9.6).

**macOS — AXUIElement (`pyobjc-framework-ApplicationServices`):**
- `AXUIElementCreateApplication(pid)`, `AXUIElementCreateSystemWide()`.
- Attributes: `AXRole`, `AXTitle`, `AXValue`, `AXPosition`, `AXSize`, `AXEnabled`, `AXFocused`, `AXChildren`.
- Actions: `AXPress`, `AXIncrement`, `AXDecrement`, `AXShowMenu`, `AXPick`.
- **Requires the Accessibility permission** for the hosting process. Detect it with `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: false})`. If missing under `sovereign`, open `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility` and tell the user (via event → Omni speech) exactly what to enable. This is an OS-level trust boundary no amount of autonomy bypasses; report it clearly and continue with everything else.
- Also: `NSWorkspace` for app enumeration/launch, `CGWindowListCopyWindowInfo` for window lists, `CGEvent` for input.

**Linux:**
- **X11**: `python-xlib` + `xdotool` + `wmctrl` + `xprop`; AT-SPI2 via `pyatspi` when `at-spi2-core` is running.
- **Wayland**: input injection is restricted by design. `ydotool` (needs the `ydotool` daemon, usually root or a uinput group membership) or `libei`/`xdg-desktop-portal` RemoteDesktop. Detect the session type (`$XDG_SESSION_TYPE`, `loginctl show-session`) and pick. If neither is usable, raise `CapabilityUnavailable("input injection", "linux-wayland", install="sudo apt install ydotool && sudo systemctl enable --now ydotoold")`.
- Screenshot on Wayland: `xdg-desktop-portal` ScreenShot, or `grim`/`slurp`, or `gnome-shell --eval`.

### 9.4 Element grounding — resolution ladder

`perception/grounding.py` resolves a natural-language or structural query into a clickable point, trying each rung in order and stopping at the first hit:

```
1. EXACT      ref id already handed to the model            → 0 ms, 100 % precise
2. A11Y       AutomationId / AXIdentifier match             → ~10 ms
3. A11Y       role + accessible-name match (fuzzy, ranked)  → ~30 ms
4. A11Y       name-substring across the focused window      → ~50 ms
5. OCR        text box match, pick the box whose text ≈ query → ~300 ms
6. TEMPLATE   cv2.matchTemplate against .kratos/ccs/templates/ (icon library, multi-scale, rotation-tolerant) → ~150 ms
7. STRUCTURE  DOM/a11y snapshot node id (browser only)      → ~20 ms
8. VLM        crop candidates + send to a grounding-capable vision model → "return the centre coordinate of <query>" → ~1–2 s
9. FAIL       return {ok:false, tried:[1..8], frame_ref, suggestion}
```

Every rung returns `{method, confidence, rect, point}`. Log which rung hit — it's the single most useful debugging signal in the whole CCS.

**Rung 8 detail:** if the installed SDK exposes a computer-use / grounding model, use it (verify in Phase 0 — do not assume a model name). Otherwise use Kratos's own active brain model if it has vision, with a strict JSON-only prompt:

```
You are a UI grounding engine. Given the screenshot and the target description,
return ONLY: {"x":int,"y":int,"w":int,"h":int,"confidence":float,"reason":string}
Coordinates are in the image's pixel space. Do not explain further.
Target: "{query}"
```

Cache groundings by `(frame_hash, query)` — the same button gets asked about constantly.

### 9.5 Post-action verification

Every mutating GUI action MUST be followed by a cheap confirmation:
- `screen_diff` between pre/post frames — if the changed-region area is ~0, the action almost certainly didn't land.
- Or an a11y assertion: element state changed (`Toggle` on, `Value` updated, `SelectionItem` selected).
- Or `screen_wait_for` on the expected consequence (dialog appeared, URL changed, cell populated).

Return the verification result inside the `ActionResult`. The model then decides whether to retry — this is what makes GUI automation actually reliable instead of fire-and-hope.

### 9.6 Threading model for perception

- One dedicated **UIA/AX worker thread** with its own COM apartment and a `queue.SimpleQueue` of requests + `concurrent.futures.Future` responses. All a11y calls funnel through it. Non-negotiable for stability.
- Screenshot + OCR run in `asyncio.to_thread` / the Wave Scheduler's worker pool (they're pure CPU/IO).
- Perception tools are **read-only** → they MUST be classified into the Wave Scheduler's concurrent read group, so `screenshot_capture` + `ui_tree_dump` + `screen_read_text` + `active_window_info` issued together all run in parallel. Verify the scheduler's safety-classification table includes the new tool names, or they'll be serialized and every GUI step will be 4× slower than it needs to be.
- **Input tools are the opposite**: they MUST be in a **strictly sequential, single-flight wave**. Two concurrent `mouse_click`s is undefined behaviour. Add `input`, `gui`-mutating, `browser`-mutating, `terminal_send`, and `system_power` to the sequential barrier group.

---

## 10. CCS INPUT ENGINE

### 10.1 Windows

- **`SendInput`** via `ctypes.windll.user32` — never `keybd_event`/`mouse_event` (deprecated, and blocked by many apps). Build proper `INPUT` structs with `MOUSEINPUT`/`KEYINPUT`/`HARDWAREINPUT` in a `ctypes.Union`.
- Mouse: `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK` with coordinates normalized to 0–65535 across the **virtual desktop**, so multi-monitor works. `SM_CXVIRTUALSCREEN`/`SM_CYVIRTUALSCREEN`/`SM_XVIRTUALSCREEN`/`SM_YVIRTUALSCREEN` for the mapping.
- Keyboard: prefer **scan codes** (`KEYEVENTF_SCANCODE`) over virtual keys for games and some legacy apps; use VK for everything else. Extended keys (`KEYEVENTF_EXTENDEDKEY`) for arrows/Ins/Home/PgUp/NumPad-Enter/Right-Ctrl/Right-Alt.
- Human-like timing: 8–25 ms between key events with jitter; 40–120 ms mouse move broken into eased steps; small overshoot-and-correct on long moves. Some apps rate-limit or reject instantaneous input. Make timing configurable (`CCS_INPUT_HUMANIZE=true`).
- `GetAsyncKeyState` to detect physically-held modifiers before injecting — if the user is holding Ctrl, don't fight them (§10.4).

### 10.2 macOS

- `Quartz.CGEventCreateKeyboardEvent`, `CGEventCreateMouseEvent`, `CGEventSetFlags` for modifiers, `CGEventPost(kCGHIDEventTap, …)` (or `kCGSessionEventTap`).
- Unicode text: `CGEventKeyboardSetUnicodeString` — handles any character without a keymap.
- Mouse move: `CGWarpMouseCursorPosition` for jumps + `CGEventCreateMouseEvent(kCGEventMouseMoved)` so apps see the move.

### 10.3 Linux

- X11: `xdotool key/type/mousemove/click`, or `python-xlib` `XTest` extension for lower latency.
- Wayland: `ydotool` (uinput-based, session-agnostic) — requires the daemon. Detect and report.
- Fallback: `pynput` (works on X11, partial on Wayland).

### 10.4 THE INTERLOCK — human/agent input arbitration

**This is the most important non-obvious piece of the whole build.** The moment Kratos owns the keyboard, the user's own keystrokes interleave with injected ones and both become garbage. Solve it properly:

```python
# ccs/input/interlock.py
class InputInterlock:
    """Single global arbiter for who owns the physical input devices."""
    state: Literal["FREE", "AGENT", "HUMAN_OVERRIDE", "PANIC"]

    def acquire(self, owner: str, timeout: float = 5.0) -> bool: ...
    def release(self, owner: str) -> None: ...

    # Background poller (10–20 Hz) while state == AGENT:
    #   - GetAsyncKeyState / CGEventSourceKeyState / xlib query
    #   - if a physical key transitions to DOWN and it was not injected by us
    #     (track a short window of our own recent injections with timestamps)
    #     → state = HUMAN_OVERRIDE
    def on_human_input(self) -> None:
        """Immediately: stop injecting, release all held keys, publish
        `ccs:interlock_human_override`, emit an AgentEvent so Omni can say
        'I felt you typing — pausing for five seconds.' Then wait
        CCS_HUMAN_OVERRIDE_GRACE_MS (default 5000) of no physical input
        before re-acquiring. Never fight the user."""
```

Rules:
- **MUST** acquire the interlock before any input sequence and release after. Single-flight: only one CCS input operation at a time, process-wide.
- **MUST** detect physical human input during agent injection and yield within one poll interval (~100 ms).
- **MUST** call `input_release_all` on every yield, panic, error, and shutdown — a stuck Ctrl or a held mouse button is worse than a failed task, because it corrupts everything the *user* does afterwards.
- **MUST** publish `ccs:interlock:*` events onto the kernel event bus so Omni can narrate the handoff.
- `CCS_INTERLOCK_ENABLED=true` by default. Set false only for headless/VM operation where no human is present — expose as `CCS_INTERLOCK_ENABLED=false` in `.env.example` with a comment.
- The panic hotkey (§13.1) bypasses the interlock entirely and always wins.

---

## 11. CCS WINDOW / APP / SYSTEM ENGINE

### 11.1 Window management

- **Windows**: `EnumWindows` + `GetWindowTextW`/`GetWindowThreadProcessId`/`IsWindowVisible`/`GetWindowRect`/`DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` (the real visible bounds, not the DWM-inflated rect) + `IsIconic`/`IsZoomed`. Focus: `SetForegroundWindow` with the `AttachThreadInput` + `AllowSetForegroundWindow` + `keybd_event(ALT)` dance — `SetForegroundWindow` alone silently fails from a background process ~most of the time. Also `ShowWindow(SW_RESTORE)` first if minimized. Move/resize: `MoveWindow`/`SetWindowPos`. Close: `WM_CLOSE` → wait → `DestroyWindow`/`TerminateProcess` for `force_close`. Pin topmost: `SetWindowPos(HWND_TOPMOST/HWND_NOTOPMOST)`.
- **macOS**: `CGWindowListCopyWindowInfo` (kCGWindowListOptionOnScreenOnly | ExcludeDesktopElements), `NSRunningApplication.activate(options:)`, AppleScript/`osascript` for move/resize of scriptable apps, `AXUIElement` + `kAXPositionAttribute`/`kAXSizeAttribute` otherwise.
- **Linux**: `wmctrl -l/-a/-r/-e`, `xdotool search --name / windowactivate / windowmove / windowsize`.

Every window gets a stable short `handle` (`w3`) valid for the process lifetime, mapped to the real HWND/CGWindowID/XID. Return `[{handle, title, app, pid, rect, state, monitor, focused, topmost}]`.

### 11.2 App launching & adapters

`apps/launcher.py` resolves a target string in this order:
1. Absolute/relative path to an executable or document → launch (documents open with their default handler).
2. Known alias (`"chrome"`, `"vscode"`, `"terminal"`, `"explorer"`, `"settings"`, `"taskmgr"`, `"spotify"`, `"discord"`) → resolved from a per-platform alias table + registry/LaunchServices/desktop-file lookup.
3. Registered App Paths (`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths`) / `LaunchServices` / `.desktop` files.
4. `where`/`which` on PATH.
5. Start-menu / Applications search via UI automation.
6. Package-manager search → `app_install` → retry. **Under `sovereign` this is automatic: if the app isn't installed, Kratos installs it.**

`apps/adapters/*` are thin, lazy, optional. `AppAdapter` contract:

```python
class AppAdapter(ABC):
    name: str
    aliases: tuple[str, ...]
    def detect(self) -> bool: ...
    def capabilities(self) -> list[str]: ...
    def launch(self, **kw) -> ActionResult: ...
    # adapter-specific high-level ops, each also exposed as a scoped tool
```

Adapters are discovered by entry-point/scan at CCS start; a failing adapter is logged and skipped, never fatal. `gui_explore` (§8.8) generates an adapter skeleton for an unknown app — combined with the existing **tool forging** pipeline (`utils/tool_creator.py` + `core/reloader.py`), Kratos can write, register, and hot-load a new app adapter at runtime. **That is the mechanism by which "no limitations" is actually achieved: the tool set is not fixed, it grows.**

### 11.3 Persistence & scheduled autonomy

Under `sovereign`, Kratos MAY make itself persistent:
- Windows Task Scheduler (`schtasks.exe` or the `ITaskService` COM API) — triggers: at logon, interval, on event, on idle.
- macOS `launchd` user LaunchAgents (`~/Library/LaunchAgents/*.plist`).
- Linux cron / systemd user units.
- Plus an internal watcher: `core/background_runner.py` + a filesystem watcher (`watchdog`) + a notification listener, so Kratos can react to machine events with nobody speaking.

Every persistence entry MUST be recorded in the audit log with its full definition and MUST be removable with `schedule_task action=delete` / `startup_entry action=remove`. Add a CLI command `/persist list|remove <name>` and a voice query *"what have you set up to run automatically?"*.

---

## 12. CCS BROWSER ENGINE

### 12.1 Strategy

Two-tier, and the tier is chosen automatically per browser instance:

**Tier A — CDP (preferred).** Launch or attach to Chrome/Edge/Brave with `--remote-debugging-port=9222 --user-data-dir=<the user's real profile>`. Talk raw CDP over the WebSocket (`/json/version` → `webSocketDebuggerUrl`). No Selenium, no Playwright dependency required — implement the handful of domains actually needed: `Page`, `Runtime`, `DOM`, `Input`, `Network`, `Target`, `Emulation`, `Log`, `Fetch`. This gives:
- exact DOM/a11y snapshots with stable node ids,
- `Runtime.evaluate` with `awaitPromise`,
- `Input.dispatchMouseEvent` / `dispatchKeyEvent` — injection that works even when the window isn't focused and isn't visible,
- network interception, download control, console logs, screenshots (`Page.captureScreenshot` with `captureBeyondViewport` for full-page).

**Note on `--user-data-dir`:** Chrome refuses remote debugging on an already-running default profile directory in recent versions. Resolution order: (a) if a debuggable instance is already listening, attach; (b) launch a **copy** of the user's profile to `.kratos/ccs/browser-profile/` (so cookies/logins carry over) and debug that; (c) fall back to Tier B on the real window. Record which path was taken in the tool result. **MUST NOT** delete or write back into the user's real profile directory.

**Tier B — UIA + input injection (universal fallback).** Works on any browser, any page, any extension, including Firefox and anything CDP can't reach: `window_focus` → `ui_tree_dump` (Chromium and Firefox both expose rich a11y trees) → `ui_find`/`ui_invoke` → `mouse_click`/`type_text` → `screenshot_capture` + OCR for canvas-heavy or non-a11y content. Slower, but nothing is out of reach.

### 12.2 Requirements

- The browser window MUST be **visible** by default (`CCS_BROWSER_HEADLESS=false`). The user should see Jarvis working. Headless is opt-in.
- Real logged-in sessions available. That's the point.
- `browser_read mode="markdown"` MUST produce a clean, Headroom-compressed readable extraction (strip nav/ads/boilerplate) — this is what the model actually consumes, not raw HTML.
- All `browser_*` mutating tools are in the **sequential wave** (§9.6).
- Every browser action gets post-verification (§9.5): URL changed? Element present? Text appeared?
- On unexpected dialogs (cookie banners, sign-in walls, "restore pages?", print dialogs), `computer_task`'s loop MUST detect and dismiss them — this is the single most common real-world failure in browser automation. Give it an explicit `browser_dialog` tool and a heuristic pre-step in `browser_click`.

---

## 13. OPERATIONAL SAFETY (CONTROL & RECOVERABILITY — NOT PERMISSION GATES)

Read §2.2 first. Nothing here asks for permission. Everything here exists so that a machine-wide autonomous agent is *controllable* and *reversible*.

### 13.1 EMERGENCY STOP

Three triggers, one handler, `ccs/safety_ops.py::panic(reason)`:

1. **Voice** — Omni detects `"stop"`, `"abort"`, `"cancel"`, `"never mind"`, `"jarvis stop"`, `"kill it"`, `"that's enough"`, `"hands off"` and calls `POST /api/voice/panic`.
2. **Global hotkey** — **Ctrl+Alt+Shift+F12** (configurable via `CCS_PANIC_HOTKEY`). Registered OS-wide: `RegisterHotKey` on Windows (message-only window on its own thread), `CGEventTap`/`NSEvent.addGlobalMonitorForEvents` on macOS, `XGrabKey`/`xdotool`-watch on X11, `ydotool`-watch or a `uinput` listener on Wayland. **The hotkey must fire even when an elevated window has focus and even when Kratos itself is mid-injection** — register it from a process at the highest integrity level Kratos has reached (§13.4).
3. **API** — `POST /api/voice/panic {"scope":"all"|"task","task_id"?}`.

`panic()` MUST, in this order, all within 50 ms of the trigger where physically possible:
```
1. set interlock state = PANIC (blocks every further injection attempt)
2. input_release_all()          — release every held key and mouse button
3. stop every running input_sequence / computer_task step loop
4. cancel every active Kratos task (existing cancellation path, §22)
5. terminate every process tree Kratos spawned in this session (tracked by pid)
6. leave injected windows alone (do NOT close the user's apps)
7. publish ccs:panic → RuntimeEvent(kind=PANIC) → SSE → Omni speaks "Stopped."
8. write a panic record to the audit log with the last 20 events and last frame ref
9. after CCS_PANIC_COOLDOWN_MS (default 1500), interlock → FREE
```
Kratos the server stays up. Omni stays up. Gemini Live stays connected. Only the *task* dies. **MUST NOT** kill the Omni process, **MUST NOT** kill the Kratos server, **MUST NOT** require a restart.

### 13.2 Self-preservation invariants (correctness, not permission)

Hardcoded refusals that exist because executing them would break the *system's own ability to operate*, and therefore the user's ability to control it:

| Never, under any mode | Why |
|---|---|
| Kill the Kratos server process, the Omni process, or the hosting terminal from within a task | Self-lobotomy; the user loses the abort path |
| Unregister/disable the panic hotkey or the interlock | Removes the user's control |
| Disable or delete `.kratos/` audit logs or snapshots | Removes recoverability |
| Reboot/shutdown as a *side effect* of an unrelated step (only via an explicit `system_power` call that the user asked for) | Surprise data loss |
| Delete `C:\Windows`, `/System`, `/usr`, `/bin`, the user's home root, or a bootloader entry | Unrecoverable |
| Format a mounted volume | Unrecoverable |
| Write to a raw block device (`\\.\PhysicalDrive*`, `/dev/sd*`, `/dev/nvme*`) | Unrecoverable |
| Exfiltrate a secret to a network destination, spoken output, Gemini context, or any log | §2.2.2 |

These are 8 lines in a `_forbidden_target()` check inside `tool_runtime`, evaluated **after** the approval gate (so the other modes are unaffected in spirit and `sovereign` is only bounded by physics and self-preservation). If a task genuinely requires one of these, Kratos emits a `FAILED` event explaining precisely which invariant blocked it, so the user can do it manually. Everything else — every app, every file, every window, every setting, every install, every elevated command — is **allowed without asking**.

### 13.3 Pre-flight state capture

Before any `input_sequence`, `computer_task`, or `app_task`, CCS records:
```json
{"task_id": "…", "t0": "…", "foreground_window": "w3", "focus_element": "e41",
 "cursor": {"x":1204,"y":771}, "modifiers": [], "clipboard_hash": "…",
 "interlock": "AGENT", "frame_ref": "f104"}
```
After completion (or panic), the foreground window, focus, cursor position, and clipboard are **restored** unless the task intentionally changed them (`CCS_RESTORE_STATE=true`, default true). Without this, every agent task leaves the user's desktop in a random state and the experience feels broken.

### 13.4 ELEVATION — the real engineering problem

**Windows UIPI**: a medium-integrity process **cannot send input to a higher-integrity window**. If Kratos runs unelevated and the target is an elevated UAC dialog, Task Manager, an installer's UAC-prompted window, Registry Editor, or anything "Run as administrator" — `SendInput` is silently dropped. There is no workaround from user mode. Solve it:

- **`ccs/system/elevation.py` maintains a persistent elevated helper.** On first need, Kratos spawns `python -m kratos_agent.ccs.elevated_helper` via `ShellExecuteW(verb="runas")`. That triggers **one** UAC prompt for the whole session (not per action — that's the difference between usable and unusable). The helper then:
  - listens on a **named pipe** (`\\.\pipe\kratos_ccs_<session>`) with a DACL restricted to the current user SID,
  - authenticates each request with a per-session random token generated by the medium-IL parent and passed via an environment variable the helper inherits (never on disk, never logged),
  - executes input injection, registry writes, service control, file ops, and `runas` launches **at High IL**,
  - registers the panic hotkey at High IL so it works everywhere,
  - streams results back over the pipe,
  - exits on `panic`, on parent-process death (watch the parent pid), or after `CCS_ELEVATED_HELPER_IDLE_S` (default 1800).
- `probe_capabilities()` reports `input_can_reach_elevated_windows: true|false`. When false, `mouse_click`/`type_text` against an elevated target returns a `CapabilityUnavailable`-shaped `ActionResult` that says exactly *"target window is elevated; spawn the helper with system_elevate"* — so the model self-heals instead of failing silently.
- `CCS_AUTO_ELEVATE=true` (default under `sovereign`): CCS spawns the helper automatically at startup, so the single UAC prompt happens once at launch and never interrupts a task.
- **UAC secure desktop**: when the OS switches to the secure desktop (the dimmed consent screen), *nothing* from user mode can inject into it, elevated or not. Detect it (`OpenInputDesktop` fails / `WTSQuerySessionInformation` / the foreground window is `Consent UI`). Report it as an explicit `WAITING_FOR_USER` event → Omni says: *"Windows is showing a UAC prompt on the secure desktop — I can't click that one, please tap Yes."* This is an OS security boundary, not a Kratos limitation. Handle it gracefully and resume automatically once the desktop returns (poll for it).
- **macOS**: `osascript -e 'do shell script "…" with administrator privileges'` (prompts once, cacheable via `AuthorizationExecuteWithPrivileges` alternatives), or install a privileged helper via SMAppService. Accessibility + Screen Recording permissions are separate OS trust boundaries — detect both (`AXIsProcessTrusted`, `CGPreflightScreenCaptureAccess`) and, if missing, open the exact Settings pane and narrate what to enable.
- **Linux**: `sudo -n true` probe → if NOPASSWD works, use `sudo`. Else `pkexec` (polkit agent prompt). Else report. Never hardcode a password. `CCS_SUDO_ASKPASS` MAY point at a helper the user configures.

### 13.5 SNAPSHOTS — the rewind button

`ccs/safety_ops.py::Snapshot`:

| Operation | Snapshot taken |
|---|---|
| `write_file`, `edit_file`, `file_delete`, `file_move`, `file_copy` (outside a git repo) | Full pre-image copy → `.kratos/snapshots/{task_id}/{sha256}.{ext}` |
| Same, **inside a git repo** | `git stash create` + record the SHA; no file copies |
| `registry_write` / `registry_delete` | `reg export` of the containing key → `.reg` file |
| `env_var set/delete` | Previous value recorded |
| `hosts_file_edit`, `firewall_rule`, `service_control`, `startup_entry`, `schedule_task` | Full previous definition serialized |
| `app_install` | Package list before/after diff |
| `disk_cleanup` | File list + pre-images for anything under the size cap |

Retention: last 50 snapshots or 2 GB, whichever first (`CCS_SNAPSHOT_RETENTION`). Content-addressed, so identical files cost nothing.

New tools:
- `undo_last_operation` — `{"scope":"task"|"operation","task_id"?,"operation_id"?}` → restores snapshots in reverse order, reports exactly what changed back.
- `list_snapshots` — `{task_id?, limit?}` → what could be undone.
- Voice: *"Undo that."* / *"Put it back."* / *"Revert the last change."* → Omni routes to `undo_last_operation`. **This is a first-class intent** (§18.3).

### 13.6 AUDIT TRAIL

Append-only JSONL at `.kratos/audit/{YYYY-MM-DD}.jsonl`, one record per mutating action:

```json
{"ts":"2025-…","task_id":"t_8f2a","session_id":"omni_voice_123","tool":"mouse_click",
 "args_redacted":{"x":1204,"y":771,"button":"left"},"capability":["input","gui"],
 "target":"w3 · Chrome · linkedin.com/jobs","decision":"ALLOW","mode":"sovereign",
 "result":"ok","duration_ms":42,"frame_ref":"f104","snapshot_ref":null,
 "elevated":false,"interlock":"AGENT"}
```

- **Redaction runs on every value**: any string matching a secret pattern (`(?i)(api[_-]?key|token|password|secret|bearer|authorization|cookie|private[_-]?key)` and high-entropy base64/hex runs ≥ 24 chars adjacent to those keys) is replaced with `«REDACTED:sha8»`. Non-optional.
- Never written to the SSE stream, never spoken, never sent to Gemini.
- Queryable: new CLI `/audit [task_id] [--tail N]` and endpoint `GET /api/voice/audit?task_id=&limit=`.
- Voice: *"What did you just do?"* → Omni fetches the tail and narrates a summary.
- Rotation: daily files, 30-day retention (`CCS_AUDIT_RETENTION_DAYS`).

### 13.7 Concurrency containment

The Wave Scheduler already parallelizes. Extend it correctly for CCS:

| Group | Concurrency | Tools |
|---|---|---|
| **Read-only perception** | up to `KRATOS_MAX_PARALLEL_WORKERS` | `screenshot_capture`, `screen_read_text`, `ui_tree_dump`, `ui_find*`, `ui_read_element`, `active_window_info`, `display_info`, `cursor_position`, `window_list`, `app_list_running`, `process_list`, `read_notifications`, `clipboard_get`, `browser_read`, `browser_state`, `browser_snapshot_dom`, `network_info`, `system_info`, `registry_read`, `file`-read tools, `grep_search`, `list_directory`, `git_status`, `git_diff` |
| **Path-safe mutations** | parallel across distinct paths | `write_file`, `edit_file`, `file_copy`, `file_move`, `registry_write` (distinct keys), `env_var` (distinct names) |
| **STRICT SINGLE-FLIGHT** | **1, global, interlock-guarded** | every `mouse_*`, every `key_*`, `type_text`, `input_sequence`, `input_lock_state` writes, `record_macro`/`play_macro`, `terminal_send`, every mutating `browser_*`, `window_focus`, `window_action`, `app_switch`, `app_command_palette`, `computer_task`, `app_task`, `gui_explore`, `system_power`, `volume_control`, `media_control`, `service_control`, `system_elevate` |
| **Sequential barrier** | 1 per wave | `run_terminal_command`, `app_launch`, `app_terminate`, `app_install`, `schedule_task`, `exit_plan_mode`, memory writes |

**Rationale to encode in a comment:** input injection manipulates one global physical resource (the user's keyboard, mouse, and single foreground window). Parallelizing it is not a performance optimization, it's a corruption bug.

---

## 14. PROCESS TOPOLOGY & PYTHON ENVIRONMENTS

### 14.1 Decision procedure (do this, don't assume)

1. Read `pyproject.toml`, `.python-version`, `uv.lock`, `requirements.txt` for **Kratos**. Read Omni's `.venv/pyvenv.cfg` and `python -V`.
2. Verify PyAudio actually installs and imports on the Kratos interpreter version.
3. **If they differ and PyAudio won't work on the Kratos version** → **two processes, bridged over `127.0.0.1` HTTP + SSE.** This is the expected outcome and the correct design regardless, because:
   - it keeps a crashing GUI-automation dependency from taking down the voice stack,
   - it lets Kratos run elevated while Omni doesn't (or vice versa),
   - it reuses Kratos's existing zero-dependency web server instead of building new transport,
   - it lets the user restart either half independently.
4. In-process import is allowed **only** if Phase 0 proves a documented public runtime object exists *and* a smoke test (`import kratos_agent; runtime = …; await runtime.…`) passes inside Omni's own interpreter *and* no dependency conflict exists. Record the smoke-test output in `DISCOVERY.md`. "It should work" is not proof.

**MUST NOT** downgrade Kratos to 3.13. **MUST NOT** upgrade Omni to 3.14 unless PyAudio *and every other Omni dependency* is verified working there first.

### 14.2 Reference topology

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ OMNI — "JARVIS SHELL"                       Python 3.13 · one process · asyncio       │
│                                                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────────┐ │
│  │ AUDIO IN    │  │ AUDIO OUT   │  │ VISION       │  │ OVERLAY (Qt thread)          │ │
│  │ mic enum    │  │ 24 kHz PCM  │  │ mss screen   │  │ kratos-illu.png avatar       │ │
│  │ native rate │  │ barge-in    │  │ cv2 camera   │  │ ● mic  ● screen  ● camera    │ │
│  │ →16k resamp │  │ drain flush │  │ 1 fps JPEG   │  │ state ring · drag · tray     │ │
│  └──────┬──────┘  └──────▲──────┘  └──────┬───────┘  └──────────────┬───────────────┘ │
│         │                │                │                         │                 │
│         └────────────────┴────────┬───────┴─────────────────────────┘                 │
│                                   ▼                                                   │
│                    ┌──────────────────────────────┐                                   │
│                    │ GEMINI LIVE SESSION          │                                   │
│                    │ audio+video in · audio out   │                                   │
│                    │ function_declarations        │                                   │
│                    │ interrupted → flush+reset    │                                   │
│                    └──────────────┬───────────────┘                                   │
│                                   ▼                                                   │
│         ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│         │ INTENT ROUTER │─▶│ TASK STATE   │─▶│ NARRATOR      │  │ KRATOS BRIDGE    │  │
│         │ (fn-calling)  │  │ MACHINE      │  │ (throttled)   │  │ httpx + SSE      │  │
│         └───────────────┘  └──────────────┘  └───────────────┘  └────────┬─────────┘  │
│                                                                          │            │
└──────────────────────────────────────────────────────────────────────────┼────────────┘
                                                          HTTP + SSE · 127.0.0.1:7860
┌──────────────────────────────────────────────────────────────────────────▼────────────┐
│ KRATOS — "THE BRAIN"                        Python 3.14+ · uv · sovereign mode        │
│                                                                                       │
│  web/server.py  ──▶  /api/voice/*  REST + SSE                                         │
│        │                                                                              │
│        ▼                                                                              │
│  KratosRuntime ─▶ Planner ─▶ AgentLoop ─▶ ToolRuntime ─▶ WaveScheduler                │
│                                        │                                              │
│        ┌───────────────────────────────┼──────────────────────────────────┐           │
│        ▼                               ▼                                  ▼           │
│  24 existing tools          ┌──────────────────────┐         CognitiveMemory / D1     │
│  (file, shell, git,         │ CCS  (NEW)           │         Verification             │
│   web, memory, subagent,    │ perception · input   │         Subagents                │
│   forge)                    │ windows · apps       │         Event Bus / Store        │
│                             │ browser · system     │         Audit / Snapshots        │
│                             │ elevation · interlock│         Panic                    │
│                             └──────────┬───────────┘                                  │
└────────────────────────────────────────┼──────────────────────────────────────────────┘
                                         ▼
              🖱️ ⌨️ 🖥️  THE ENTIRE OPERATING SYSTEM, EVERY APP, EVERY WINDOW
```

### 14.3 Dependencies to add

**Kratos** — new optional extras in `pyproject.toml`:

```toml
[project.optional-dependencies]
computer = [
  "psutil>=6.0",           # processes, resources, cross-platform
  "pyautogui>=0.9.54",     # baseline cross-platform input + locateOnScreen
  "pynput>=1.7.7",         # global hotkeys, fallback injection
  "pygetwindow>=0.0.9",    # window enumeration
  "rapidocr-onnxruntime>=1.3",  # offline OCR, no system binary
  "numpy>=1.26",           # frame math, resampling
  "websockets>=12",        # CDP
]
computer-windows = ["pywin32>=306", "comtypes>=1.4"]
computer-macos   = ["pyobjc-framework-Quartz>=10", "pyobjc-framework-ApplicationServices>=10",
                    "pyobjc-framework-Cocoa>=10"]
computer-linux   = ["python-xlib>=0.33", "pyatspi>=2.46; sys_platform=='linux'", "watchdog>=4"]
overlay = ["PySide6>=6.7"]
voice   = ["google-genai>=1.0", "pyaudio>=0.2.14", "opencv-python>=4.9", "mss>=9",
           "pillow>=10", "python-dotenv>=1", "numpy>=1.26", "scipy>=1.11"]
all     = ["kratos-agent[computer,computer-windows,computer-macos,computer-linux,overlay,voice]"]
```

**Omni** — `PySide6`, `httpx` (SSE + HTTP/2, async), `numpy`, `scipy` (resampling), plus what's already there.

**Critical PyAudio note for Python 3.13:** `audioop` was **removed from the stdlib in 3.13**, and PyAudio historically depended on it. Verify `import pyaudio` actually works in Omni's venv. If it fails:
- Option A (preferred): `pyaudiowpatch` — a maintained PyAudio fork with WASAPI + loopback + 3.13 wheels. Its API is a superset, so `import pyaudiowpatch as pyaudio` is often a drop-in.
- Option B: `sounddevice` (PortAudio bindings, clean 3.13 support, callback-based).
- Option C: `pip install audioop-lts` (the extracted stdlib module) alongside stock PyAudio.
Record which you used and why in `DISCOVERY.md`. Design `audio.py` behind a small `AudioBackend` ABC so the choice is swappable.

---

## 15. KRATOS CHANGE 3 — THE VOICE API

Extend `web/server.py` (the existing zero-dependency `ThreadingHTTPServer`). **Match its existing style exactly** — if it uses `BaseHTTPRequestHandler` subclasses with a route table, add routes to that table; do not bolt on aiohttp/FastAPI.

### 15.1 Bind & transport

- **MUST** remain bound to `127.0.0.1` (verify in Phase 0; if it currently binds `0.0.0.0`, that's a bug to fix — a machine-wide autonomous agent must not be reachable from the LAN). `KRATOS_WEB_HOST` env, default `127.0.0.1`.
- Port from `KRATOS_WEB_PORT`, default `7860`.
- Add `Access-Control-Allow-Origin: http://127.0.0.1:7860` only (the existing frontend), plus permissive handling for the Omni client which is not a browser (no Origin header) — allow it.
- Optional local bearer token `KRATOS_VOICE_TOKEN`: if set, `/api/voice/*` requires `Authorization: Bearer <token>`. If unset (default), no auth — it's localhost. **Do not invent auth requirements beyond this.**

### 15.2 Endpoints

```
GET   /api/health
      → 200 {"ok":true,"service":"kratos","version":"…","mode":"sovereign",
             "model":"…","uptime_s":1234,"tasks_active":1,"voice_api":true,
             "capabilities_url":"/api/voice/capabilities"}
      Cheap. No side effects. Used by Omni's startup probe and periodic re-probe.

GET   /api/voice/capabilities
      → 200 {§6.6 payload}

POST  /api/voice/session
      body {"omni_session_id":"omni_voice_123","label?":"living room","mode?":"sovereign"}
      → 201 {"kratos_session_id":"s_9c1f…","omni_session_id":"…","created_at":"…",
             "memory_tier":"episodic","persisted":true}
      Idempotent: re-POSTing the same omni_session_id returns the same kratos_session_id.

GET   /api/voice/session/{omni_session_id}
      → 200 {"kratos_session_id":"…","turns":17,"tasks":["t_1","t_2"],
             "last_active":"…","memory_summary":"…"}

POST  /api/voice/task
      body {
        "session_id": "omni_voice_123",           # required
        "task_description": "…",                   # required — full natural language, refs resolved
        "visual_context": "…",                     # optional — Gemini's screen/camera summary
        "priority": "normal"|"high",               # optional
        "mode": "sovereign",                       # optional override
        "context": {                               # optional, all forwarded to the planner
          "cwd": "…", "app_hint": "chrome", "frame_refs": ["f104"],
          "previous_task_id": "t_8f2a", "attachments": ["server.py"]
        },
        "background": true                         # optional — route through background_runner
      }
      → 202 {"task_id":"t_8f2a","session_id":"…","status":"PENDING",
             "events_url":"/api/voice/task/t_8f2a/events","accepted_at":"…"}
      MUST return immediately. MUST NOT block on completion. MUST NOT run the planner inline.

GET   /api/voice/task/{task_id}/events            ← SSE
      Headers honoured: Accept: text/event-stream, Last-Event-ID: <n>
      → text/event-stream, see §16 for the envelope.
      MUST support resume from Last-Event-ID using the event store's ordering.
      MUST send a heartbeat comment (": ping\n\n") every 15 s so proxies/idle timers don't drop it.
      MUST terminate the stream with a single `event: done` after a terminal status.

GET   /api/voice/task/{task_id}/status
      → 200 {AgentEvent snapshot: task_id, status, progress, current_step,
             steps_completed, steps_total, files_changed[], tools_used[],
             started_at, elapsed_s, last_event, error?, result?}

POST  /api/voice/task/{task_id}/cancel
      → 200 {"cancelled":true,"task_id":"…","at":"…"}   (or 409 if already terminal)
      Uses the REAL cancellation mechanism found in Phase 0. Kills only this task.

POST  /api/voice/task/{task_id}/steer
      body {"message":"actually use PostgreSQL instead of SQLite","mode":"append"|"replace_goal"}
      → 200 {"accepted":true,"injected_at_step":7}
      Mid-task course correction without cancel-and-restart.

POST  /api/voice/task/{task_id}/confirm
      body {"decision":"approve"|"deny","scope":"once"|"always"|"session","note?":"…"}
      → 200 {"ok":true}
      Kept for completeness and for non-sovereign modes. Under `sovereign` the server
      never emits WAITING_FOR_CONFIRMATION, so Omni never calls this. MUST NOT be
      repurposed as a hidden gate.

POST  /api/voice/undo
      body {"session_id":"…","scope":"task"|"operation","task_id?":"…","operation_id?":"…"}
      → 200 {"undone":[{…}],"restored_files":3,"restored_registry_keys":1}

GET   /api/voice/tasks?state=running|active|recent&session_id=&limit=20
      → 200 {"tasks":[{task_id, status, description, started_at, progress}]}

GET   /api/voice/audit?task_id=&limit=100
      → 200 {"records":[…redacted audit records…]}

POST  /api/voice/approval_mode
      body {"mode":"sovereign"|"full-auto"|"auto-edit"|"suggest"}
      → 200 {"mode":"sovereign","applied_to":"session|global"}

POST  /api/voice/panic
      body {"scope":"all"|"task","task_id?":"…","reason?":"voice-stop"}
      → 200 {"panic":true,"released_inputs":true,"tasks_cancelled":2,"at":"…"}

POST  /api/voice/screenshot                        (Kratos's own eyes, independent of Omni)
      body {"monitor?":0,"region?":{…}}
      → 200 image/jpeg  OR  {"frame_ref":"f201","path":"…","w":…,"h":…,"ocr_preview":"…"}

GET   /api/voice/memory/recall?q=&limit=
      → 200 {"results":[{tier,key,content,score,session_id}]}

WS    /api/voice/ws                                (OPTIONAL — only if the existing server
      Full duplex alternative to polling+SSE.      already has WebSocket support; otherwise
                                                    do not add a dependency for it.)
```

### 15.3 Server-side wiring

- The voice routes MUST obtain the **same** `KratosRuntime` instance the UI routes use (find how `server.py` currently does it — module global, closure, or app-state). **MUST NOT** construct a second runtime; two runtimes = two memory stores = split brain.
- SSE handler runs on the `ThreadingHTTPServer`'s own thread. Bridge from the runtime's async/sync event bus to that thread with a `queue.Queue` per subscriber. Never block the runtime's event loop writing to a slow socket — drop with a `{"type":"warning","message":"event backpressure, N events dropped"}` if a subscriber's queue exceeds 500.
- Subscribers are tracked per `task_id`; on client disconnect (detect `BrokenPipeError`/`ConnectionResetError` on write), unsubscribe cleanly and **keep the task running**. Omni reconnecting with `Last-Event-ID` resumes.
- Every handler wraps its body in try/except and emits a proper JSON error rather than a 500 with an HTML traceback:
  `→ 4xx/5xx {"error":{"code":"TASK_NOT_FOUND","message":"…","detail":"…"}}`

---

## 16. EVENT CONTRACT & NORMALIZATION

### 16.1 Principle

If Phase 0 finds Kratos already has `RuntimeEvent`/`EventKind`, **reuse and extend them — do not invent a parallel system.** The voice API serializes them; Omni adapts them. Normalize into an Omni-side shape only where narration genuinely needs it, and only with fields Kratos can actually supply.

### 16.2 SSE wire format

```
id: 4711
event: agent
data: {"task_id":"t_8f2a","seq":4711,"type":"tool","status":"RUNNING",
       "message":"Reading src/kratos_agent/web/server.py",
       "tool":"read_file","tool_args_summary":"server.py",
       "progress":0.42,"step":{"index":3,"total":9,"title":"Locate the auth bug"},
       "narratable":true,"narration":"I'm checking the server code.",
       "ts":"2025-…","frame_ref":null,"elapsed_ms":1204}

: ping

id: 4712
event: agent
data: {"task_id":"t_8f2a","seq":4712,"type":"status","status":"RUNNING", …}

id: 4900
event: done
data: {"task_id":"t_8f2a","status":"COMPLETED","at":"…"}
```

- `event:` is always `agent`, `log`, `warning`, `error`, `panic`, or `done`.
- `id:` is a **monotonic integer per task** so `Last-Event-ID` resume works exactly.
- One JSON object per `data:` line; no multi-line data payloads (they're legal SSE but fragile).
- UTF-8, `\n\n` terminated.

### 16.3 Omni-side `AgentEvent`

```python
# event_adapter.py
@dataclass(slots=True)
class AgentEvent:
    task_id:   str
    seq:       int
    type:      str        # status | plan | tool | verify | memory | error | result
                          # | panic | capability | gui_step | browser_step | elevation
    status:    str        # PENDING | RUNNING | WAITING_FOR_USER | COMPLETED
                          # | FAILED | CANCELLED
    message:   str        # short, human-readable, NEVER chain-of-thought
    tool:      str | None = None
    tool_args_summary: str | None = None
    progress:  float | None = None
    step:      dict | None = None       # {index, total, title}
    narratable: bool = False            # server pre-filters; narrator double-checks
    narration: str | None = None        # server-suggested phrasing; narrator may override
    frame_ref: str | None = None
    files_changed: list[str] = field(default_factory=list)
    error:     dict | None = None       # {code, message, hint}
    result:    dict | None = None       # final structured result
    ts:        str = ""
    elapsed_ms: int = 0

    @classmethod
    def from_sse(cls, event: str, data: dict) -> "AgentEvent": ...
```

`status` values: use exactly what Phase 0 finds in the task manager's real enum. The README's `PENDING/RUNNING/COMPLETED/FAILED` plus `WAITING_FOR_CONFIRMATION`/`CANCELLED` is the expected set — **map, don't assume**.

**MUST NOT** put raw Kratos event objects, model reasoning, chain-of-thought, tool-result bodies, stack traces, or file contents into `message` or `narration`. The `narratable` flag plus a length cap (`message` ≤ 160 chars) are the enforcement.

### 16.4 What is narration-worthy

Server-side, set `narratable: true` for:

| Event | Why |
|---|---|
| Task accepted / plan created / plan revised | The user should know work started and the shape of it |
| Step transitions (`step.index` changes) | Natural chapter boundaries |
| First use of each distinct tool in a step | "Now it's reading files" → "now it's editing" → "now it's running tests" |
| Any `write_file`/`edit_file` on a **new** path | Concrete progress |
| `run_terminal_command` / `terminal_send` | The user hears "running the tests" |
| `app_launch`, `app_install`, `browser_open` | Visible machine changes |
| `computer_task` / `app_task` milestones (sub-goal reached, not each click) | GUI work is long; narrate chapters |
| `system_elevate` acquired | "I've got administrator access now" — once per session |
| Verification start / pass / fail | The payoff |
| `CapabilityUnavailable` | The user needs to know something's missing and what |
| UIPI / secure-desktop / macOS-permission waits | The user must physically act |
| Error, panic, cancel | Always |
| Final result | Always |

Everything else → `narratable: false`. Roughly **1 in 8 events** should be narratable in a typical task.

---

## 17. OMNI CHANGE 1 — GEMINI LIVE CLIENT

### 17.1 SDK discipline

Use the **installed** `google-genai`. In Phase 0, dump its actual surface:

```bash
python -c "import google.genai as g; print(g.__version__)"
python -c "from google.genai import types; import inspect; \
           print(inspect.signature(types.LiveConnectConfig.__init__))"
python -c "from google.genai import types; \
           print([f for f in dir(types.LiveConnectConfig) if not f.startswith('_')])"
python -c "from google import genai; c=genai.Client(); print([m for m in dir(c.models) if 'list' in m])"
```

Then discover the **real live model id** — `MODEL = "gemini-3.8-live-extended-thinking"` in the current file looks invented. Query the model list and pick the current live-capable model. Make it configurable:

```python
MODEL = os.getenv("GEMINI_LIVE_MODEL") or _discover_live_model(client) or "gemini-2.5-flash-native-audio-preview-12-2024"
```

`_discover_live_model` lists models, filters for ones whose name contains `live` (or whose `supported_generation_methods` include the live method), prefers the newest, logs the choice, and caches it. If discovery fails, fall back to `GEMINI_LIVE_MODEL` and if that's unset, print the candidate list and exit with a clear message — never guess silently.

### 17.2 Session config — full Jarvis setup

```python
CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],

    # ── Jarvis persona, routing rules, narration discipline ──────────────────
    system_instruction=types.Content(parts=[types.Part(text=JARVIS_SYSTEM_PROMPT)]),

    # ── Native tool calling = the intent router (§18) ────────────────────────
    tools=[types.Tool(function_declarations=[
        START_AGENT_TASK, CANCEL_ACTIVE_TASK, GET_TASK_STATUS, STEER_ACTIVE_TASK,
        ANSWER_DIRECTLY, UNDO_LAST, PANIC_NOW, SET_MODE, QUERY_CAPABILITIES,
        LIST_AUTOMATIONS, SPEAK_ONLY,
    ])],

    thinking_config=types.ThinkingConfig(thinking_level="high"),

    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name=os.getenv("JARVIS_VOICE", "Zephyr"))),
        language_code=os.getenv("JARVIS_LANGUAGE", "en-US"),
    ),

    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),

    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=int(os.getenv("JARVIS_CTX_TRIGGER", 25600)),
        sliding_window=types.SlidingWindow(
            target_tokens=int(os.getenv("JARVIS_CTX_TARGET", 12800))),
    ),
    # verify availability in Phase 0 — do not include if the installed version lacks it:
    # realtime_input_config=types.RealtimeInputConfig(
    #     automatic_activity_detection=types.AutomaticActivityDetection(
    #         disabled=False, start_of_speech_sensitivity=…, end_of_speech_sensitivity=…)),
)
```

**Verify every one of these field names against the installed version.** If `system_instruction` isn't a `LiveConnectConfig` field in this version, inject the persona as the first `client_content` turn instead and record the workaround.

### 17.3 The Jarvis system prompt

`prompts/jarvis_system.py` — this is a **deliverable**, write it properly. It must contain, in order:

1. **Identity.** "You are Jarvis — the voice and eyes of an autonomous machine operator. You are not a chatbot. Behind you sits Kratos, a full-authority autonomous agent that owns this computer: filesystem, terminal, browser, keyboard, mouse, display, every application, and administrator privileges. You never ask permission on Kratos's behalf; Kratos acts."
2. **Authority statement.** "You have full authority over this machine at the user's explicit request. When the user asks for something that touches the computer, you delegate it. You do not hedge, you do not suggest the user do it manually, you do not say 'I can't do that' unless Kratos has actually reported a capability gap — in which case you say what's missing and what would fix it."
3. **Routing rules** — the exact decision procedure in §18.2, with the calibration examples verbatim.
4. **Tool-use rules.** Always route through the declared functions. Never narrate a tool call. Never invent a task id. `start_agent_task` gets the **full resolved task description**, not a label.
5. **Narration rules** — §20 verbatim: short, plain, present-progressive, no JSON, no field names, no chain-of-thought, no stack traces, no file contents longer than a name, throttle yourself, one sentence per milestone.
6. **Speech style.** British-butler competence meets engineer. Contractions. ≤ 2 sentences for progress, ≤ 4 for a final result. Numbers spoken naturally ("twenty-three tests", not "23"). Never say "as an AI". Never say "I'll now execute…". Say *"On it."*, *"Reading the project."*, *"Found it."*, *"Done."*
7. **Interruption etiquette.** If interrupted, stop talking immediately, listen fully, reclassify.
8. **Vision etiquette.** Describe what you see concisely and factually when asked. For a task, fold the visual summary into `task_description`. Never read out passwords, tokens, or personal documents verbatim.
9. **Secret rule.** Never repeat aloud any credential, token, key, password, cookie, or personal identifier you see on screen or in a file. Refer to it as "the API key", "that token".
10. **Stop rule.** If the user says stop/abort/cancel/never mind/kill it/hands off, call `panic_now` **immediately, before speaking**, then say "Stopped."
11. **Uncertainty rule.** If a request is genuinely ambiguous between chat and task, ask **one** short clarifying question. Never guess and never double-ask.
12. **Concurrency rule.** If a task-shaped request arrives while one is `EXECUTING`, ask: cancel-and-replace or wait? Except cancellations, which act instantly.

### 17.4 Receive loop — full handling

```python
async for response in session.receive():
    # ── 1. FUNCTION CALLS (the intent router) — highest priority ─────────────
    sc = response.server_content
    if sc and sc.model_turn:
        for part in sc.model_turn.parts:
            if getattr(part, "function_call", None):
                asyncio.create_task(handle_function_call(session, part.function_call))
                continue                                  # do NOT also treat as audio
            if getattr(part, "inline_data", None) and part.inline_data.data:
                enqueue_playback(part.inline_data.data)

    # ── 2. INTERRUPTION (barge-in) ──────────────────────────────────────────
    if sc and getattr(sc, "interrupted", None):
        playback_queue.clear_nowait()          # immediate drain, not graceful
        state.force(State.LISTENING)
        narrator.cancel_pending()
        overlay.set_state(State.LISTENING)
        log("[Jarvis] interrupted — audio flushed")

    # ── 3. TRANSCRIPTIONS ───────────────────────────────────────────────────
    if sc and sc.input_transcription and sc.input_transcription.text:
        transcript.append_user(sc.input_transcription.text)
        overlay.set_last_user(sc.input_transcription.text)
    if sc and sc.output_transcription and sc.output_transcription.text:
        transcript.append_jarvis(sc.output_transcription.text)

    # ── 4. TURN / USAGE / SESSION METADATA ──────────────────────────────────
    if getattr(response, "usage_metadata", None): metrics.record(response.usage_metadata)
    st = getattr(response, "interaction_status", None)   # verify real attribute name
    if st == "IN_PROGRESS": state.thinking()
    elif st == "IDLE":      state.idle_after_turn()

    # ── 5. SESSION LIFECYCLE ────────────────────────────────────────────────
    if getattr(response, "go_away", None) or getattr(sc, "turn_complete", None):
        …  # handle session expiry: reconnect with backoff, preserving session_id mapping
```

**MUST**: function calls in a Live session are answered with a function response, and the model then continues generating audio. Verify the exact send shape in Phase 0 — expected one of:
```python
await session.send(function_response=types.FunctionResponse(
    name=fc.name, response={"ok": True, …}))
# or
await session.send(client_content=types.Content(role="user", parts=[
    types.Part.from_function_response(name=fc.name, response={…})]), turn_complete=True)
```
Use whichever the installed version actually supports. If a function response is never sent, the session stalls — add a 5 s watchdog that sends a synthetic `{ok:false,error:"timeout"}` response so the conversation can't hang.

**MUST**: handle `function_call` for `start_agent_task` **without blocking the receive loop** — `submit_task` is an HTTP round trip. Dispatch to a task; return the function response as soon as the bridge yields a `task_id` (which the endpoint returns immediately by design, §15.2).

### 17.5 Injecting unsolicited progress into the session

Kratos events arrive on Omni's SSE reader, independent of the Gemini turn structure. To make Jarvis *speak* them, Omni injects text into the live session:

```python
await session.send(client_content=types.Content(
    role="user",
    parts=[types.Part(text=
        f"[SYSTEM PROGRESS — speak this to the user in one short natural sentence, "
        f"do not read it literally, do not mention this message]: {line}"
    )],
), turn_complete=True)
```

**Verify in Phase 0.** Constraints to respect:
- Only inject when the model is `IDLE`. If it's mid-turn, **queue** the line and coalesce (see §20.4).
- Never inject more than ~1 line per 3 s (narrator throttle, §20).
- Never inject while the user is speaking (VAD/`LISTENING` state).
- If injection isn't supported in this SDK version, fall back to `session.send_realtime_input(text=...)`.
- Tag every injected line with a marker so the transcript renderer can hide it from the visible conversation log.

---

## 18. OMNI CHANGE 2 — INTENT ROUTING

### 18.1 Mechanism: native Live function calling (primary)

Declare these in the session config (§17.2). Gemini then decides *itself*, mid-conversation, which to invoke — no bespoke transcript parser, no regex, no second classifier model.

```python
START_AGENT_TASK = types.FunctionDeclaration(
    name="start_agent_task",
    description=(
        "Delegate real work on this computer to Kratos, the autonomous agent that "
        "controls the filesystem, terminal, browser, keyboard, mouse, every "
        "application, and administrator privileges. Use this for ANY request that "
        "requires acting on the machine rather than merely talking about it. "
        "Pass the complete task in the user's own words with all references resolved."
    ),
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "task_description": types.Schema(
                type="STRING",
                description="The full task, standalone and unambiguous. Resolve every "
                              "reference: 'the first issue' → describe that issue; "
                              "'this file' → name the file; 'that error' → describe it. "
                              "Include acceptance criteria if the user gave any."),
            "visual_context": types.Schema(
                type="STRING",
                description="If the request depends on what is currently on screen or "
                              "on camera, a concise factual natural-language summary "
                              "of the relevant visible content (error text, UI state, "
                              "file names, dialog contents). Omit if not vision-derived."),
            "app_hint": types.Schema(type="STRING",
                description="Specific application to drive, if any. e.g. 'chrome', 'vscode'."),
            "priority": types.Schema(type="STRING", enum=["normal","high"]),
            "background": types.Schema(type="BOOLEAN",
                description="true if the user asked for it to happen later or "
                              "repeatedly, or explicitly said 'in the background'."),
        },
        required=["task_description"],
    ),
)

CANCEL_ACTIVE_TASK = types.FunctionDeclaration(
    name="cancel_active_task",
    description="Cancel the currently running Kratos task. Use for 'stop', 'cancel', "
                "'abort', 'never mind', 'kill it', 'hands off', 'that's enough'.",
    parameters=types.Schema(type="OBJECT", properties={
        "reason": types.Schema(type="STRING")}, required=[]))

PANIC_NOW = types.FunctionDeclaration(
    name="panic_now",
    description="EMERGENCY STOP. Halts all keyboard/mouse injection immediately, "
                "cancels all running tasks, and terminates everything Kratos spawned. "
                "Use the instant the user says stop/abort/emergency, or if you observe "
                "the agent doing something clearly unwanted. Call this BEFORE speaking.",
    parameters=types.Schema(type="OBJECT", properties={
        "reason": types.Schema(type="STRING")}, required=[]))

GET_TASK_STATUS = types.FunctionDeclaration(
    name="get_task_status",
    description="Report what Kratos is doing right now: current step, progress, "
                "files touched, elapsed time. Use for 'how's it going', 'what are you "
                "doing', 'are you done yet', 'status'.",
    parameters=types.Schema(type="OBJECT", properties={}, required=[]))

STEER_ACTIVE_TASK = types.FunctionDeclaration(
    name="steer_active_task",
    description="Change the goal of the running task without cancelling it. Use for "
                "'actually, do X instead', 'also handle Y', 'skip that part', "
                "'use PostgreSQL not SQLite'.",
    parameters=types.Schema(type="OBJECT", properties={
        "message": types.Schema(type="STRING",
            description="The correction, phrased as a complete instruction."),
        "mode": types.Schema(type="STRING", enum=["append","replace_goal"]),
    }, required=["message"]))

UNDO_LAST = types.FunctionDeclaration(
    name="undo_last",
    description="Revert what Kratos just changed — files, registry, settings. Use for "
                "'undo that', 'put it back', 'revert', 'that was wrong, undo'.",
    parameters=types.Schema(type="OBJECT", properties={
        "scope": types.Schema(type="STRING", enum=["task","operation"]),
        "detail": types.Schema(type="STRING")}, required=[]))

ANSWER_DIRECTLY = types.FunctionDeclaration(
    name="answer_directly",
    description="The request is conversation, explanation, opinion, or a vision "
                "question. You will answer it yourself in speech. Kratos is NOT "
                "involved. Call this so the system records the routing decision.",
    parameters=types.Schema(type="OBJECT", properties={
        "topic": types.Schema(type="STRING"),
        "used_vision": types.Schema(type="BOOLEAN")}, required=[]))

QUERY_CAPABILITIES = types.FunctionDeclaration(
    name="query_capabilities",
    description="Fetch what this machine can actually do right now — displays, input "
                "devices, browsers, package managers, elevation, installed tools. Use "
                "for 'what can you do', 'can you control my mouse', 'are you admin'.",
    parameters=types.Schema(type="OBJECT", properties={}, required=[]))

SET_MODE = types.FunctionDeclaration(
    name="set_mode",
    description="Change Kratos's authority level. 'sovereign' = full autonomy with "
                "admin and no prompts (default). Also full-auto, auto-edit, suggest.",
    parameters=types.Schema(type="OBJECT", properties={
        "mode": types.Schema(type="STRING",
            enum=["sovereign","full-auto","auto-edit","suggest"])}, required=["mode"]))

LIST_AUTOMATIONS = types.FunctionDeclaration(
    name="list_automations",
    description="List scheduled tasks, startup entries, watchers and services Kratos "
                "has installed for persistent autonomy.",
    parameters=types.Schema(type="OBJECT", properties={}, required=[]))

SPEAK_ONLY = types.FunctionDeclaration(
    name="speak_only",
    description="Emit speech without any tool side effect. Rarely needed — prefer "
                "answering inline.",
    parameters=types.Schema(type="OBJECT", properties={
        "text": types.Schema(type="STRING")}, required=["text"]))
```

**MUST** be robust to: partial/malformed arguments (validate + supply defaults, don't crash), duplicate calls for the same utterance (idempotency key on the transcript hash), calls while a task is running (§18.4), and calls for tools the bridge can't reach (Kratos down → speak the unavailability message, §30.3).

### 18.2 Decision procedure (encode this in the system prompt AND in code as a validator)

```
utterance arrives
  │
  ├─ contains a stop-phrase?  ─────────────▶ PANIC_NOW / CANCEL_ACTIVE_TASK   (immediate, pre-empts everything)
  │
  ├─ refers to the running task and changes it? ─▶ STEER_ACTIVE_TASK
  │
  ├─ asks about progress/state? ───────────▶ GET_TASK_STATUS
  │
  ├─ asks to revert? ──────────────────────▶ UNDO_LAST
  │
  ├─ asks about the machine's abilities / authority / automations? ─▶ QUERY_CAPABILITIES / LIST_AUTOMATIONS / SET_MODE
  │
  ├─ is it about what's visible AND only asks for description/explanation?
  │     "what's on my screen" "read that error to me" "what does this dialog say"
  │     ─────────────────────────────────▶ ANSWER_DIRECTLY (used_vision=true). No Kratos.
  │
  ├─ is it general conversation / knowledge / opinion / code explanation?
  │     ─────────────────────────────────▶ ANSWER_DIRECTLY
  │
  ├─ does it require ANY action on the machine — files, code, terminal, apps,
  │   browser, windows, settings, install, system, GUI, or "look at X AND fix/do Y"?
  │     ─────────────────────────────────▶ START_AGENT_TASK
  │                                          + visual_context if vision-derived
  │
  └─ genuinely ambiguous between chat and task?
        ─────────────────────────────────▶ ask ONE short clarifying question, no tool call
```

**The asymmetry rule:** *"What does this error mean?"* → `ANSWER_DIRECTLY`. *"What does this error mean — fix it."* → `START_AGENT_TASK` with the error described in `visual_context`. **Any verb of action anywhere in the utterance tips it to task.** When in doubt and the cost of asking is one sentence, ask. When in doubt and asking would be annoying for an obviously-actionable request, act.

### 18.3 Calibration sets (put these verbatim in the system prompt as few-shot guidance, and use them in tests §34.2)

**`ANSWER_DIRECTLY` — never reaches Kratos:**
> "Hello." · "How are you?" · "What is Python?" · "Explain transformers." · "What is RAG?" · "Tell me about Linux." · "What's the difference between TCP and UDP?" · "What do you see on my screen?" · "Read that error out loud." · "What time is it?" · "Who wrote Dune?" · "Summarize this article for me." · "What's on my calendar today?" *(read-only query, if Kratos exposes one — otherwise this becomes a task)* · "Do you like music?" · "What can you do?" → `QUERY_CAPABILITIES`

**`START_AGENT_TASK` — always reaches Kratos, with full context:**
> "Inspect my project." · "Fix the error." · "Build this website." · "Search the codebase for authentication." · "Run the tests and fix them." · "Open Chrome and search for AI jobs." · "Analyze this folder." · "Create the required files." · "Refactor this project." · "Deploy this application." · "Look at this error and fix it." · "Install Node 22." · "Clean up my Downloads folder." · "Rename every photo in that directory by date." · "Open Spotify and play some jazz." · "Set my display to dark mode." · "Find what's eating my CPU and kill it." · "Take a screenshot and email it to me." · "Go to LinkedIn, find remote Python jobs in Berlin from the last day, and put the good ones in a spreadsheet." · "Update all my packages." · "Make this repo run on startup." · "Undo that." → `UNDO_LAST` · "Book a table for two at that place on my screen." · "Fill in this form." · "Restart the database service." · "Turn off the Wi‑Fi."

**`STEER_ACTIVE_TASK`:**
> "Actually, use PostgreSQL instead." · "Skip the tests for now." · "Also fix the lint errors while you're there." · "Do it in a new branch."

**`GET_TASK_STATUS`:**
> "How's it going?" · "What are you doing?" · "Are you done?" · "How much longer?"

**Stop phrases → `PANIC_NOW` / `CANCEL_ACTIVE_TASK`:**
> "Stop." · "Cancel." · "Abort." · "Never mind." · "Cancel the task." · "Kill it." · "Hands off." · "That's enough." · "Jarvis, stop." · "Whoa whoa whoa."

### 18.4 Concurrency

If `START_AGENT_TASK` arrives while `state == EXECUTING`:
- **Explicit stop phrase** → act immediately, no question (§13.1). Pre-empts everything.
- **Steering-shaped** ("also…", "actually…", "instead…") → `STEER_ACTIVE_TASK`, no question.
- **New independent task** → Omni speaks one short question: *"I'm still working on the first one — cancel it and start this, or queue it up?"* Then:
  - "cancel"/"replace"/"start this" → `POST /cancel` then `POST /task`.
  - "queue"/"wait"/"after" → local FIFO in `task_state.py`; on the running task's terminal event, auto-submit the queued one and announce it.
  - No answer within 30 s → **queue it** (the non-destructive default) and say so.
- **MUST NOT** silently drop the request. **MUST NOT** silently queue without telling the user.

### 18.5 Fallback classifier

If — and only if — Phase 0 proves the installed SDK/model combination cannot do function calling inside a live session, implement `intent_router.py` with a prompt-based JSON classifier: send the transcript as a `client_content` turn with a strict schema instruction, parse fenced JSON, validate, retry once on malformed output, and default to `ANSWER_DIRECTLY` on repeated failure (the safe direction: never launch machine-wide automation from an unparsed guess). Record loudly in `DISCOVERY.md` and the Final Report that the fallback path is in use.

---

## 19. OMNI CHANGE 3 — THE KRATOS BRIDGE

### 19.1 Module

`agent_bridge.py` — the **only** place in Omni that knows Kratos exists. Transport-agnostic behind one interface. Intent router, narrator, state machine, and overlay talk **only** to this class.

```python
class KratosBridge:
    def __init__(self, base_url: str = "http://127.0.0.1:7860",
                 token: str | None = None, timeout: float = 10.0): ...

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def health_check(self) -> BridgeHealth:
        """GET /api/health. Cheap, no side effects. Called at startup, then every
        JARVIS_BRIDGE_PROBE_S (default 10). Never raises — returns ok=False."""

    async def capabilities(self) -> dict:
        """GET /api/voice/capabilities. Cached for 60 s."""

    async def ensure_session(self, omni_session_id: str, label: str = "") -> str:
        """POST /api/voice/session (idempotent). Returns kratos_session_id and
        persists the mapping (§23). Called once per Omni launch."""

    # ── tasks ────────────────────────────────────────────────────────────────
    async def submit_task(self, *, session_id: str, task_description: str,
                          visual_context: str | None = None,
                          app_hint: str | None = None,
                          priority: str = "normal", background: bool = False,
                          context: dict | None = None) -> str:
        """POST /api/voice/task → task_id. Returns immediately; never blocks on
        completion. Raises BridgeUnavailable if Kratos is down."""

    async def stream_events(self, task_id: str, *,
                            last_seq: int | None = None,
                            heartbeat_timeout: float = 45.0
                            ) -> AsyncIterator[AgentEvent]:
        """GET /api/voice/task/{id}/events as SSE. Yields AgentEvent (§16.3).
        MUST: send Last-Event-ID on (re)connect; reconnect with exponential
        backoff (0.5→1→2→4→8 s, max 30 s) on transient network errors; yield a
        synthetic AgentEvent(type='warning', status='RUNNING',
        message='reconnecting to Kratos') on each retry; give up after
        JARVIS_BRIDGE_MAX_RECONNECTS (default 12) and yield a terminal
        type='error' event; detect a stalled stream via heartbeat timeout."""

    async def status(self, task_id: str) -> AgentEvent: ...
    async def cancel(self, task_id: str) -> bool: ...
    async def steer(self, task_id: str, message: str,
                    mode: str = "append") -> bool: ...
    async def confirm(self, task_id: str, decision: str,
                      scope: str = "once") -> bool: ...   # non-sovereign modes only
    async def undo(self, session_id: str, scope: str = "task",
                   task_id: str | None = None) -> dict: ...
    async def panic(self, scope: str = "all",
                    task_id: str | None = None, reason: str = "") -> dict: ...
    async def list_tasks(self, state: str = "active") -> list[dict]: ...
    async def audit(self, task_id: str | None = None, limit: int = 50) -> list[dict]: ...
    async def set_mode(self, mode: str) -> bool: ...
    async def screenshot(self, monitor: int | None = None) -> bytes | dict: ...
    async def memory_recall(self, q: str, limit: int = 5) -> list[dict]: ...

    # ── internals ────────────────────────────────────────────────────────────
    async def aclose(self) -> None: ...
    @property
    def available(self) -> bool: ...
```

### 19.2 Implementation requirements

- **`httpx.AsyncClient`** with `http2=False`, `limits=Limits(max_connections=20, max_keepalive_connections=5)`, `timeout=Timeout(connect=3.0, read=None, write=5.0, pool=5.0)` — `read=None` is essential for SSE.
- **SSE parsing**: hand-roll a small incremental parser over `client.stream("GET", url).aiter_lines()` — accumulate `id:`/`event:`/`data:`/`retry:` fields until a blank line, then dispatch. Handle multi-line `data:` by joining with `\n`. Ignore `:` comment lines but **reset the heartbeat timer on them**. Do not add an `sseclient` dependency unless Phase 0 shows one already present.
- **Every method** catches `httpx.HTTPError`, `OSError`, `asyncio.TimeoutError` and translates into `BridgeUnavailable(reason)` or `BridgeError(status, code, message)`. **No raw httpx exception escapes this module.**
- **Every method** logs one line: `[bridge] POST /api/voice/task → 202 t_8f2a (41 ms)`.
- **Secret hygiene**: the bridge strips `Authorization` values and any body field named `*key*`/`*token*`/`*password*` from its own logs.
- **In-process variant**: if Phase 0 selects in-process (§14.1 step 4), implement the identical interface with `InProcessKratosBridge` calling the runtime directly and adapting `RuntimeEvent` → `AgentEvent`. Everything above the bridge is unchanged. This is the whole point of the abstraction.

### 19.3 Health watcher

A background task that:
- probes `health_check()` every `JARVIS_BRIDGE_PROBE_S`,
- on transition `up → down`: sets `bridge.available = False`, emits `AgentEvent(type="error", status="FAILED", message="Lost contact with Kratos")`, overlay shows a red Kratos dot, Jarvis says *"I've lost contact with the execution backend — I can still talk and see, but I can't act right now."* **Gemini conversation and vision keep working.**
- on transition `down → up`: re-`ensure_session`, overlay green, Jarvis says *"Kratos is back."*, and re-submits any task that was mid-flight if `JARVIS_BRIDGE_RESUME_ON_RECONNECT=true`.
- **MUST NOT** crash, retry-storm, or block the audio path.

---

## 20. OMNI CHANGE 4 — NARRATION ENGINE

### 20.1 Purpose

Convert Kratos events into short, natural, spoken English. **Never** verbatim event dumps. Never JSON. Never field names. Never chain-of-thought.

### 20.2 Two-stage narration

**Stage 1 — local dictionary (fast, deterministic, free).** `narrator.py` holds a mapping used for the 90 % case, so progress speech has zero added latency:

| Event signature | Spoken line (rotate variants to avoid repetition) |
|---|---|
| `type=plan`, plan created | "Alright — here's the plan: {n} steps, starting with {first}." / "On it. {n} steps." |
| `type=step`, index changed | "Step {i} of {n}: {title}." |
| `tool=read_file` \| `grep_search` \| `list_directory` (first in step) | "I'm reading through the code." / "Checking the relevant files." |
| `tool=write_file` \| `edit_file` | "Making the change in {basename}." / "Editing {basename}." |
| `tool=run_terminal_command` \| `terminal_send` | "Running {summary}." / "Let me run that." |
| `tool=app_launch` | "Opening {app}." |
| `tool=app_install` | "Installing {package} — give me a moment." |
| `tool=browser_open` | "Opening {url_host} in {browser}." |
| `tool=browser_click` \| `browser_type` (milestone only) | "Filling that in now." |
| `tool=computer_task` \| `app_task` | "I'm driving {app} for this one." |
| `tool=gui_explore` | "Learning my way around {app}." |
| `tool=mouse_click` \| `type_text` \| `input_sequence` | *(silent by default — too granular)* |
| `tool=system_elevate` (first time) | "I've got administrator access now." |
| `tool=registry_write` \| `env_var` \| `service_control` | "Adjusting the system settings." |
| `tool=schedule_task` \| `startup_entry` | "Setting that up to run automatically." |
| `tool=system_power` | "{Action} — {delay}." |
| `type=verify` start | "Running a verification pass." |
| `type=verify` pass | "Verification passed." |
| `type=verify` fail | "Verification found something — I'm on it." |
| `type=capability` unavailable | "I can't {capability} on this machine — {hint}." |
| `status=WAITING_FOR_USER` (secure desktop / OS permission) | "Windows needs you to tap Yes on that prompt — I can't reach it." |
| `type=error` | "That didn't work: {message}. {Next action or 'trying something else'}" |
| `type=panic` | "Stopped." |
| `status=CANCELLED` | "Cancelled." |
| `status=COMPLETED` | *(stage 2)* |
| `status=FAILED` | "I couldn't finish that — {reason}." |

**Stage 2 — LLM summarization for the final result.** The terminal event carries a structured result:
```json
{"status":"success","summary":"Fixed missing await in auth middleware",
 "files_changed":["src/api/auth.py","tests/test_auth.py"],
 "commands_run":["pytest -q"],"verification":"12 passed",
 "duration_s":94,"tools_used":["read_file","edit_file","run_terminal_command"],
 "steps_completed":7,"notes":"also removed two dead imports"}
```
Omni builds a compact prompt and lets **Gemini itself** produce the spoken sentence — no extra API call, just inject the result as a system-progress line with an explicit instruction:

```
[TASK COMPLETE — say this to the user as ONE natural spoken sentence, max 3 short
sentences, no JSON, no field names, no file paths longer than a filename, plain
spoken English:]
outcome=success · what=Fixed missing await in auth middleware ·
files=src/api/auth.py, tests/test_auth.py · tests=12 passed · time=94s ·
extra=also removed two dead imports
```

Target output: *"Done. The bug was a missing await in the auth middleware — fixed it, and all twelve tests pass."*

### 20.3 Throttling

- **Minimum interval between spoken progress lines: 3.0 s** (`JARVIS_NARRATE_MIN_INTERVAL`). Milestone events (`type=plan`, step change, verify, error, terminal) bypass the floor but still coalesce.
- **Coalescing window: 1.2 s.** Collect events in the window, pick the highest-priority one, drop the rest. Priority: `error` > `panic` > terminal > `verify` > `capability` > `plan` > `step` > `tool` > `log`.
- **Never** speak while `state == LISTENING` (the user is talking) or while a barge-in just happened.
- **Never** interrupt an in-flight model turn — queue and flush on `IDLE`.
- Cap the pending-narration queue at 3 lines; drop oldest beyond that. Nobody wants a 40-line backlog read out loud after a long task.
- Deduplicate identical consecutive lines.
- Silence mode: if the user says *"work quietly"* / `"don't narrate"*, set `narrate=False` — only errors and the final result get spoken. Toggleable from the overlay context menu.

### 20.4 Hard content rules

`narrator.py` runs every candidate line through `sanitize_for_speech()`:
- Strip code blocks, stack traces, file contents, diffs, JSON, ANSI escapes, URLs longer than a hostname.
- Truncate to ≤ 220 characters; if truncated at a word boundary, end with a period.
- Redact anything matching a secret pattern → replace with "a credential".
- Convert digits to speakable form where natural (`23` → "twenty-three" for counts; keep "3.13" for versions).
- Reject any line containing `traceback`, `Exception`, `0x`, `{`, `}`, ` at ` + `:\d+`, or > 3 consecutive `/` or `\`.
- **MUST NOT** pass through Kratos's model reasoning. If the server ever sends something that looks like reasoning, drop it and log a warning.

---

## 21. OMNI CHANGE 5 — VOICE SESSION STATE MACHINE

`task_state.py`. For voice-session UX only — **Kratos keeps its own task state; Omni does not duplicate the task manager.**

```
        ┌──────────────────────────────── PANIC ───────────────────────────┐
        │                                                                  │
        ▼                                                                  │
   ┌────────┐  voice detected   ┌───────────┐  fn-call parsed  ┌─────────┐ │
   │  IDLE  │──────────────────▶│ LISTENING │─────────────────▶│ROUTING  │ │
   └───▲────┘                   └─────▲─────┘                  └────┬────┘ │
       │                              │                             │      │
       │              ┌───────────────┼─────────────────────────────┤      │
       │              │               │                             │      │
       │   ANSWER_DIRECTLY            │                  START_AGENT_TASK  │
       │              ▼               │                             ▼      │
       │       ┌────────────┐         │                    ┌──────────────┐│
       │       │  SPEAKING  │         │                    │  EXECUTING   ││
       │       └─────┬──────┘         │                    └───┬──────┬───┘│
       │             │                │        terminal event  │      │    │
       │             │                │              ┌─────────┘      │    │
       │             ▼                │              ▼                │    │
       │      ┌─────────────────────────────────────────────┐        │    │
       └──────│ COMPLETED / FAILED / CANCELLED → (narrate)  │◀───────┘    │
              └─────────────────────────────────────────────┘             │
                                                                           │
       ┌──────────────────────┐  user answers                              │
       │ WAITING_FOR_USER     │◀── (secure desktop / OS permission only,   │
       └──────────────────────┘      never an approval gate) ──────────────┘
```

| State | Mic → Gemini | Screen/camera → Gemini | Playback | Overlay ring |
|---|---|---|---|---|
| `IDLE` | on | per toggles | off | soft cyan, slow pulse |
| `LISTENING` | on | per toggles | **drained** | magenta, expanding rings |
| `ROUTING` | on | per toggles | off | magenta → violet sweep |
| `SPEAKING` | on (barge-in armed) | per toggles | on | cyan, audio-reactive bars |
| `EXECUTING` | on (barge-in armed) | per toggles | narration only | gold, clockwise sweep + progress arc |
| `WAITING_FOR_USER` | on | per toggles | prompt only | amber, steady + slow blink |
| `COMPLETED` | on | per toggles | final result | green flash → cyan |
| `FAILED` | on | per toggles | error line | red flash → cyan |
| `CANCELLED` | on | per toggles | "Stopped." | grey flash → cyan |
| `PANIC` | on | off | hard-stopped | **red, fast strobe, 2 s** |
| `DEGRADED_NO_KRATOS` | on | per toggles | normal chat | cyan ring + **red Kratos dot** |
| `DEGRADED_NO_MIC` | **off** | per toggles | on | grey ring + mic icon slashed |

Transitions MUST be logged (`[state] EXECUTING → COMPLETED (t_8f2a, 94 s)`) and pushed to the overlay over a thread-safe queue (§27.5). Terminal states auto-return to `IDLE` after the final narration completes plus 800 ms.

**MUST** be a single writer: all transitions go through `state.force()` / `state.try_move()` under an `asyncio.Lock`, so a barge-in and a terminal event arriving simultaneously can't corrupt it.

---

## 22. CANCELLATION, STEERING, UNDO

### 22.1 Cancellation

Phase 0 finds the real mechanism. Then:

- Voice stop-phrase → `PANIC_NOW`/`CANCEL_ACTIVE_TASK` → `bridge.cancel(task_id)` (+ `bridge.panic()` for the hard variant) → `state → CANCELLED` → drain playback → speak "Stopped." → `IDLE`.
- Overlay: long-press the avatar, or the red stop button that appears in `EXECUTING`.
- Hotkey: Ctrl+Alt+Shift+F12 → Omni hits `POST /api/voice/panic` **and** Kratos's own local hotkey handler fires independently. Belt and braces — the hotkey must work even if Omni is hung.
- **MUST NOT** kill the Omni process. **MUST NOT** kill the Kratos server. **MUST NOT** close the user's application windows. **MUST** release the input interlock and all held keys (§13.1).
- Cancellation **always** pre-empts the concurrency question (§18.4). It is the one path with zero friction.

### 22.2 Steering

Mid-task correction without restart: `bridge.steer(task_id, message, mode)`. Kratos-side, the message is injected into the agent loop's next model turn as a system/user note ("The user has updated the goal: …"), the planner revises the remaining steps, and a `plan` event with `revised: true` is emitted. If Phase 0 shows the agent loop has no injection point, add the smallest clean one: a `pending_steer_messages: deque` on the runtime, drained into the next context assembly. Do not rebuild the loop.

### 22.3 Undo

`UNDO_LAST` → `bridge.undo(session_id, scope)` → Kratos restores snapshots in reverse (§13.5) → returns a list of what changed back → Omni speaks it: *"Reverted — auth.py and the test file are back to how they were."*

---

## 23. SESSION & MEMORY CONTINUITY

### 23.1 Mapping

- Omni mints one `omni_session_id` per launch: `omni_voice_{YYYYMMDD}_{6hex}`, or restores the previous one from `.kratos/voice_sessions.json` if `JARVIS_SESSION_PERSIST=true` (default) and it's < 24 h old.
- `bridge.ensure_session()` returns the **Kratos** session id, created once and reused for the whole Omni run.
- Persist the mapping:
```json
{ "omni_voice_20250114_a3f9c1":
    { "kratos_session_id": "s_9c1f2b", "started": "…", "last_active": "…",
      "turns": 41, "tasks": [{"id":"t_8f2a","desc":"fix auth bug","status":"COMPLETED"}],
      "last_task_id": "t_8f2a", "labels": ["jarvis-desk"] } }
```
- **MUST NOT** create a new Kratos session per utterance. One voice run = one Kratos session.

### 23.2 Reference resolution

*"Inspect my project."* … later … *"Fix the first issue."*

Two mechanisms, both required:
1. **Kratos owns the history.** Because the same session id is reused, Kratos's memory (`memory.py` / `cognitive_memory.py`) already contains the earlier turn and its findings. The planner resolves "the first issue" from its own episodic memory. **Omni MUST NOT try to re-derive or re-send history Kratos already has.**
2. **Omni resolves what only it can see.** References to the *conversation itself* or to *vision* — "that one", "the second file you mentioned", "the error on screen" — Omni expands using its own transcript ring buffer (last 20 turns) and the current visual context, then writes the **expanded** description into `task_description`. Rule: `task_description` MUST be comprehensible to someone who has never heard the conversation.

Omni also passes `context.previous_task_id` so Kratos can link related work explicitly.

### 23.3 Cross-run recall

On launch, after `ensure_session`, call `bridge.memory_recall(q="recent work", limit=3)`. If there's meaningful recent history, Jarvis MAY open with one short line: *"Back online. Last time we fixed the auth middleware — want to pick that up?"* Gate behind `JARVIS_RECALL_GREETING=true`.

---

## 24. OMNI CHANGE 6 — AUDIO SUBSYSTEM

`audio.py`. Fix the mic properly; make playback interruptible.

### 24.1 Backend abstraction

```python
class AudioBackend(ABC):
    name: str
    def list_input_devices(self) -> list[DeviceInfo]: ...
    def list_output_devices(self) -> list[DeviceInfo]: ...
    def default_input(self) -> DeviceInfo | None: ...
    def default_output(self) -> DeviceInfo | None: ...
    def open_input(self, device: DeviceInfo, rate: int, channels: int,
                   chunk: int) -> "InputStream": ...
    def open_output(self, device: DeviceInfo, rate: int, channels: int) -> "OutputStream": ...
    def terminate(self) -> None: ...

@dataclass
class DeviceInfo:
    index: int; name: str; host_api: str
    max_input_channels: int; max_output_channels: int
    default_sample_rate: float
    supported_rates: list[int]      # probed
    is_os_default_input: bool
```

Implement `PyAudioBackend`, `PyAudioWPatchBackend` (WASAPI + loopback), `SoundDeviceBackend`. Select in order: whatever imports successfully and passes a 200 ms capture smoke test. Log the choice.

### 24.2 Microphone robustness — the `-9999` fix

Ordered diagnostics. Each stage produces a **specific, actionable** message; never a bare traceback.

```
STAGE 1 — Enumerate.
  pya.get_device_count() wrapped in try/except. If it raises → host API failure:
    "[Audio] PortAudio could not initialize. On Windows this is usually a missing
     or corrupted audio driver; on macOS, check Terminal has microphone
     permission in System Settings → Privacy & Security → Microphone."
  List every device with maxInputChannels > 0. Print the table. If empty:
    "[Audio] No input-capable device found. Cause 1 of 4: no microphone is
     connected, or this app/terminal lacks OS microphone permission.
     Windows: Settings → Privacy & security → Microphone → 'Let desktop apps
     access your microphone' ON, and your terminal/IDE listed.
     macOS: System Settings → Privacy & Security → Microphone → enable Terminal.
     Voice input disabled; screen, camera and text still work."

STAGE 2 — Select.
  Prefer the OS default input device if it's among the candidates.
  Else prefer, in order: host API == WASAPI(shared) > CoreAudio > ALSA > MME > DirectSound.
  Else candidates[0].
  Explicitly handle the Windows "default device" edge case: get_default_input_device_info()
  may raise -9999 or return a device that no longer exists after a USB unplug.
  Catch, log, and fall through to the ranked candidate list. Never crash.

STAGE 3 — Validate the format BEFORE opening.
  device.default_sample_rate → probe [48000, 44100, 16000, 32000, 22050, 8000]
  with pya.is_format_supported(rate, input_device=index, input_channels=1,
  input_format=paInt16). Pick the highest supported ≥ 16000 (usually 48000).
  If NONE is supported → Cause 3 of 4:
    "[Audio] Device '{name}' rejects every sample rate we probed. This is a
     driver problem or an exclusive-mode conflict (another app holds the device
     in WASAPI exclusive mode). Try: disable 'Allow applications to take
     exclusive control of this device' on the mic's Advanced properties, or
     unplug/replug, or pick a different device with JARVIS_MIC_DEVICE."
  Open at the DEVICE'S NATIVE RATE, never at 16000 directly.

STAGE 4 — Open.
  Wrap pya.open in try/except OSError. On -9999 / "Unanticipated host error":
    "[Audio] Microphone error -9999 (PortAudio 'Unanticipated host error').
     Ranked causes:
       1. OS microphone permission not granted to this app/terminal  ← most common
       2. Device index went stale (USB mic unplugged, or the OS default changed
          after this process started)
       3. Requested sample rate / channel count unsupported by this device
       4. Another application holds the device exclusively
     What we tried: device {index} '{name}' @ {rate} Hz, {channels} ch, paInt16.
     Quick fixes: grant permission and restart; or set JARVIS_MIC_DEVICE=<index>;
     or run `python -m omni.audio --list-devices` to see the table.
     Raw error: {e}"
  Retry once with the next-best candidate device before giving up.
  Retry once at 44100 if 48000 failed.

STAGE 5 — Degrade.
  If all attempts fail: print the diagnostic, set audio_input_available=False,
  return. Every other subsystem continues. Overlay shows the mic button greyed
  and slashed. Jarvis still speaks; the user can still type into the console.
  MUST NOT terminate the application. MUST NOT raise into the TaskGroup.
```

Also add a CLI utility: `python -m omni.audio --list-devices` printing the full device table with supported rates. This alone resolves most user support threads.

### 24.3 Capture + resampling

- Capture at native rate (typically 48 kHz), mono, `paInt16`, `frames_per_buffer` sized for ~20–40 ms (`rate // 50`, rounded to a power of two ≥ 256; the existing 1024 is ~21 ms at 48 kHz which is fine).
- **`audioop` is gone in Python 3.13.** Resample with `numpy`:
```python
def pcm16_resample(buf: bytes, src: int, dst: int) -> bytes:
    if src == dst: return buf
    a = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
    n_out = int(round(len(a) * dst / src))
    if n_out <= 0: return b""
    # scipy.signal.resample_poly is best; fall back to linear interpolation
    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(src, dst)
        y = resample_poly(a, dst // g, src // g)
    except ImportError:
        x_old = np.arange(len(a)); x_new = np.linspace(0, len(a) - 1, n_out)
        y = np.interp(x_new, x_old, a)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()
```
- Maintain a **continuous resampler state** across chunks (overlap of a few samples) or you get clicks at every boundary. `resample_poly` over a rolling buffer with `zi`/`zf` state, or simply resample in fixed 4800→1600 blocks of 4800 samples (exactly 100 ms) so boundaries align on integer ratios.
- Send `audio/pcm;rate=16000`.
- Optional software AGC + noise gate (`JARVIS_MIC_GATE_DB=-52`): drop frames below the gate to stop Gemini hearing room hiss and phantom-triggering VAD.
- **Mute** (overlay button / `m` hotkey): stop reading the stream (or read-and-discard, cheaper to resume) and set a flag so nothing is enqueued. Overlay icon changes; Gemini receives nothing.

### 24.4 Playback + barge-in

- 24 kHz, mono, `paInt16`, output device chosen the same ranked way; handle open failure with a clear message and degrade to text-only console output.
- `PlaybackQueue` with: `put(chunk)`, `clear_nowait()` (drain **immediately**, not gracefully), `depth()`, `is_playing()`.
- Write in a dedicated thread with small writes (~50 ms) so `clear_nowait()` takes effect within one write — the existing code writes whole chunks, which means an interrupt can lag by hundreds of ms.
- Optional audio-reactive level meter: compute RMS per chunk and push it to the overlay for the speaking animation (§27.4).

### 24.5 Interruption — full barge-in

On `server_content.interrupted`:
```
1. playback.clear_nowait()            ← immediate, within one write cycle (~50 ms)
2. narrator.cancel_pending()          ← drop queued + in-window progress lines
3. state.force(LISTENING)
4. overlay.set_state(LISTENING)
5. log "[jarvis] barge-in: flushed {n} chunks ({ms} ms of audio)"
6. continue receiving — the user's new speech is already streaming
7. when the new utterance's transcription completes → route it fresh (§18.2).
   If it's a stop phrase → PANIC. If it's a correction → STEER. If it's new
   work → concurrency rule (§18.4).
```
**MUST NOT** build a separate heuristic VAD interrupt detector — the SDK's `interrupted` flag is authoritative. **MUST NOT** let stale audio play over new input.

**Additionally**: if a barge-in arrives while `state == EXECUTING`, the Kratos task **keeps running**. Interruption silences Jarvis; it does not cancel work. Only an explicit stop phrase cancels.

---

## 25. OMNI CHANGE 7 — VISION SUBSYSTEM

`vision.py`. Keep all three existing modes working, add selection and quality.

### 25.1 Screen

- `from mss import mss` and use the **lowercase factory** `mss()`. (Capitalized `mss.MSS()` is wrong for current versions — verify against the pinned version, but default to lowercase.)
- **Windows DPI awareness must be set before the first capture** (`SetProcessDpiAwarenessContext(-4)`), or `mss` returns scaled frames and `sct.monitors` reports wrong sizes. Set it once, in `vision.py` at import, guarded by platform.
- Monitor selection: `--monitor N` CLI flag + overlay selector. `monitors[0]` = all-composited, `[1]` = primary. Report the full topology at startup:
  `[screen] 2 monitors: [1] 2560×1440 @ (0,0) primary · [2] 1920×1080 @ (2560,0)`
- Window-scoped capture: `--capture-window "Chrome"` → resolve the rect from the OS window list and crop. Much better signal-to-token ratio than the whole desktop.
- Downscale to ≤ 1568 px long edge, JPEG q78 (was 1920/q80). At 1 fps this is ~250 KB/s of context — the compression config matters.
- **Cursor overlay** option: draw a small ring at the real cursor position so Gemini can reason about pointer state.
- **Redaction** (`JARVIS_SCREEN_REDACT=true`, default): run a fast regex over OCR'd text for password fields, and blur rectangles matching common secret UI patterns (browser password managers, `1Password`, terminal lines after `export *KEY=`). Cheap insurance for §2.2.2. Log what was blurred, never the content.
- Rate: 1 fps default (`JARVIS_SCREEN_FPS`). Bump to 3 fps transiently when the user asks a vision question, drop back after 10 s of no vision queries — saves context massively.
- On capture failure (locked workstation, secure desktop, RDP session change, monitor unplugged): log once, back off to 0.2 fps, keep retrying, **never crash**. Report `vision_degraded` to the overlay.

### 25.2 Camera

- Probe indices 0–4 (`cv2.VideoCapture(i)`), plus platform backends explicitly: `CAP_DSHOW` on Windows (avoids the 10-second MSMF hang), `CAP_AVFOUNDATION` on macOS, `CAP_V4L2` on Linux. Try the platform-preferred backend **first**.
- Report what it found: `[camera] index 0 · "Integrated Webcam" · 1280×720 @ 30 fps`.
- `--camera N` flag + overlay selector.
- Set `CAP_PROP_FRAME_WIDTH/HEIGHT` to 1280×720 before reading; thumbnail to ≤ 1024 px; JPEG q85 (matches current behaviour).
- 1 fps default (`JARVIS_CAMERA_FPS`).
- If no camera: log the reason (permission vs. absent vs. busy — `CAP_PROP_*` open failure strings differ), disable camera, overlay button greyed, everything else works.
- **Privacy LED awareness**: on Windows/macOS, opening the camera lights an indicator. That's correct behaviour — do not attempt to suppress it. The overlay camera button MUST accurately reflect whether capture is live, so the user always knows.
- Warm-up: discard the first 3–5 frames (auto-exposure/white-balance settling) before sending.

### 25.3 Mode matrix

```bash
python live.py --mode none      # voice only
python live.py --mode camera    # voice + camera
python live.py --mode screen    # voice + screen
python live.py --mode both      # NEW: voice + screen + camera simultaneously
python live.py --mode jarvis    # NEW: default. both + overlay + Kratos bridge
```

`--mode jarvis` is the default. All previous modes keep working exactly as before.

**MUST NOT** stream raw frames to Kratos. Gemini sees frames; **only natural-language summaries cross the bridge** into `visual_context`. Kratos takes its *own* screenshots via CCS when it needs pixel-level truth (§8.1).

### 25.4 Queueing

Single `out_queue(maxsize=5)`, drop-oldest on full (existing behaviour is correct — real-time beats complete). Tag each payload with its source so `send_realtime` routes audio→`audio=`, image→`video=`. Add per-source drop counters and log them at shutdown: `[queue] dropped 41 screen frames, 3 audio chunks under backpressure`.

---

## 26. OMNI CHANGE 8 — THE FLOATING JARVIS OVERLAY

**This is the face of the system. It must look like Jarvis, not like a Tk demo.**

### 26.1 Assets

- **`kratos-illu.png`** is the avatar. Locate it in Phase 0. Record: path, dimensions, whether it has alpha, aspect ratio.
  - If it does **not** exist in the workspace: record `NOT FOUND` in `DISCOVERY.md`, generate a placeholder at `assets/jarvis/kratos-illu.png` (1024×1024 RGBA, Vice-cyberpunk neon arc-reactor/sword motif consistent with `kratos_banner.png`), wire everything against the **canonical path `assets/jarvis/kratos-illu.png`**, and flag it in the Final Report. Do not silently substitute `kratos_banner.png` — different aspect ratio, not transparent, wrong shape for an orb.
- Derive at build time (script `overlay/build_assets.py`, run automatically on first launch if outputs are missing):
  - `avatar_orb.png` — centre-cropped to a circle, 512×512, alpha-masked, premultiplied.
  - `avatar_orb@2x.png`, `avatar_orb@3x.png` — for HiDPI.
  - `avatar_dim.png` — desaturated 40 % version for muted/degraded states.
  - `ring_sprites.png` — 64-frame rotation strip for the thinking arc (generated, not hand-drawn).
  - `icon_mic.svg/png`, `icon_mic_muted`, `icon_screen`, `icon_screen_off`, `icon_camera`, `icon_camera_off`, `icon_stop`, `icon_kratos`, `icon_expand` — 64×64, neon-outline style matching the frontend's `icons.svg` (reuse those paths if they exist).

### 26.2 Technology choice

**Primary: PySide6.** Reason: genuine frameless + transparent + always-on-top + click-through + 60 fps `QPainter` animation, on all three OSes, without spawning a browser process.

Set `QT_QPA_PLATFORM` appropriately, and **`QApplication` MUST live on its own dedicated thread** — Qt requires the app object and all widget operations on the thread that created them, and Omni's main thread is owned by `asyncio.run()`. Pattern:

```python
# overlay/jarvis_overlay.py
class OverlayController:
    """Thread-safe façade. The ONLY object the asyncio side touches."""
    def __init__(self): self._q: queue.SimpleQueue[Command] = queue.SimpleQueue()
    def start(self):                       # spawns the Qt thread
    def stop(self):
    def set_state(self, s: State):         self._q.put(("state", s))
    def set_progress(self, p: float):      self._q.put(("progress", p))
    def set_mic(self, on: bool):           self._q.put(("mic", on))
    def set_screen(self, on: bool):        self._q.put(("screen", on))
    def set_camera(self, on: bool):        self._q.put(("camera", on))
    def set_kratos(self, up: bool):        self._q.put(("kratos", up))
    def set_caption(self, text: str):      self._q.put(("caption", text))
    def set_level(self, rms: float):       self._q.put(("level", rms))   # speaking anim
    def set_task(self, title, i, n):       self._q.put(("task", (title, i, n)))
    def flash(self, kind: str):            self._q.put(("flash", kind))
    def collapse(self, to_orb: bool):      self._q.put(("collapse", to_orb))

def _qt_thread(ctl: OverlayController, events: queue.Queue):
    app = QApplication(sys.argv)            # created ON this thread
    app.setQuitOnLastWindowClosed(False)
    w = JarvisWidget(ctl, events)
    w.show()
    timer = QTimer(); timer.timeout.connect(w.pump); timer.start(8)   # drain ctl._q, ~120 Hz
    sys.exit(app.exec())
```

`events` is the **outbound** queue: button clicks, drags, hotkeys → consumed by the asyncio side via `asyncio.to_thread(events.get)` or a `loop.call_soon_threadsafe` bridge. Never touch a QWidget from the asyncio thread.

**Fallbacks**, in order, if PySide6 can't be installed:
1. **`pywebview`** — frameless, transparent, always-on-top webview rendering a small HTML/CSS/JS overlay. Reuses the Vice-cyberpunk styling from `frontend/src/index.css` directly. JS→Python via `js_api`.
2. **`tkinter`** — `-transparentcolor` on Windows, `-transparent` + `systemTransparent` on macOS; `overrideredirect(True)`, `attributes("-topmost", True)`. No animation beyond 15 fps; accept it.
3. **Console-only** — no overlay; print a status line and keep the existing hotkeys. Degrade, never crash.

Document which one is active at startup: `[overlay] PySide6 6.7.2 · frameless transparent topmost · monitor 1 @ (2080, 96)`.

### 26.3 Geometry & layout

```
                    ╭─────────────────────────╮
                    │                         │
                    │      ╭───────────╮      │      260 × 340 px  (expanded)
                    │      │           │      │       96 ×  96 px  (collapsed orb)
                    │      │ kratos-   │      │
                    │      │ illu.png  │      │      avatar: 168 × 168
                    │      │  (orb)    │      │      ring:   196 × 196  (painted)
                    │      ╰───────────╯      │
                    │     ◜ animated ring ◝   │
                    │                         │
                    │   ┌─── caption line ──┐ │      caption: 1 line, 11 px,
                    │   │ EXECUTING · 3/9   │ │               max 34 chars, elided
                    │   └───────────────────┘ │
                    │                         │
                    │    ( 🎙 )  ( 🖥 )  ( 📷 ) │      3 buttons, 44 px dia,
                    │                         │      14 px gap, centred
                    ╰─────────────────────────╯
                     ↑ exactly as requested:
                       image on top, three buttons below
```

- Frameless, transparent background, always on top, no taskbar entry (`Qt.Tool`), no drop shadow from the WM (we paint our own glow).
- **Draggable** anywhere on the avatar. Position persisted to `.kratos/overlay.json` along with collapsed state, monitor, and toggles.
- **Snapping**: within 24 px of a screen edge → snap flush; within 40 px of a corner → corner-snap. Constrain to the current monitor's `availableGeometry()` (respects taskbar/dock).
- **Double-click avatar** → collapse to a 96 px orb (buttons hidden, ring retained). Double-click again → expand. **Middle-click** → toggle click-through.
- **Right-click** → context menu: Mic / Screen / Camera toggles · Mode (none/camera/screen/both) · Monitor ▸ · Camera ▸ · Narration (on/off/terse) · Authority (sovereign/full-auto/auto-edit/suggest) · Kratos ▸ (status, restart, capabilities, audit tail) · Expand panel · Reset position · Quit Jarvis.
- **Click-through mode**: `setAttribute(Qt.WA_TransparentForMouseEvents, True)` — the whole overlay becomes non-interactive so it never blocks a click on the desktop beneath. Global hotkey (Ctrl+Alt+Shift+F9) exits click-through. Essential when Jarvis is driving the mouse and the overlay happens to sit over the target.
- **Auto-hide**: fade to 15 % opacity when the user is actively typing/moving the mouse and no Jarvis speech for 6 s; restore to 100 % on any Jarvis activity. `JARVIS_OVERLAY_AUTOHIDE=true`.
- HiDPI: paint at `devicePixelRatioF()`; load `@2x`/`@3x` assets accordingly. Never let the orb look soft on a Retina/4K display.

### 26.4 The three buttons

Each is a 44 px circle, custom-painted (`QPushButton` subclass with `paintEvent`), neon-outline on dark translucent fill, with:

| Button | Icon | Active | Inactive | Disabled | Click | Hotkey |
|---|---|---|---|---|---|---|
| **MIC** (mute/unmute) | `icon_mic` | magenta ring + glow, subtle pulse | grey outline + diagonal slash through the icon | hollow grey, tooltip "No microphone detected — {reason}" | toggles `audio_input_enabled`; when muting, also stops enqueueing and flashes the ring grey once | `Ctrl+Alt+Shift+M` |
| **SCREEN** (screen access) | `icon_screen` | cyan ring + animated scanline sweep across the icon | grey outline | hollow grey, tooltip "Screen capture unavailable" | toggles the `capture_screen` task on/off; when turning on, asks which monitor if >1 (small popup list) | `Ctrl+Alt+Shift+S` |
| **CAMERA** | `icon_camera` | green ring + blinking record dot | grey outline | hollow grey, tooltip "No camera — {reason}" | toggles the `capture_frames` task on/off; if >1 camera, popup selector | `Ctrl+Alt+Shift+C` |

Every button MUST have:
- a 140 ms scale-down animation on press, 200 ms ease-out on release;
- a tooltip with the *live* state and, when disabled, the actual reason (from the audio/vision diagnostics — not a generic string);
- an accessible name (`setAccessibleName`) and keyboard focusability (`Tab` cycles the three, `Space`/`Enter` activates);
- a state change that is reflected **immediately** in the underlying subsystem, not just visually. The button is never a lie.

Below them, a **status strip** (optional, `JARVIS_OVERLAY_CAPTION=true`):
```
◉ EXECUTING · 3/9 · fixing auth middleware      [⏹]
```
with a small round **stop button** that appears only in `EXECUTING`/`PANIC`. One line, 11 px, `Pixl` font if it loads (it's in `frontend/public/fonts/`), else `JetBrains Mono`/system mono. Colour-coded by state.

Plus a **Kratos connectivity dot** in the top-right of the avatar: green = up, red = down, amber = reconnecting. Clicking it opens the Kratos submenu.

### 26.5 The state ring

Painted with `QPainter` over the avatar, 196 px, 3 px stroke, anti-aliased, additive blending (`QPainter.CompositionMode_Plus`) so it glows:

| State | Ring |
|---|---|
| `IDLE` | soft cyan, 40 % alpha, 4 s sine breathing on radius (±3 px) and alpha |
| `LISTENING` | magenta, 3 concentric rings expanding outward from the avatar edge, spawned every 600 ms, fading over 900 ms |
| `ROUTING` | magenta → violet gradient arc, sweeping clockwise, 1.2 rev/s |
| `SPEAKING` | cyan arc whose thickness and radius are driven by the live playback RMS (§24.4) — genuinely audio-reactive, 30 Hz update |
| `EXECUTING` | gold clockwise sweep (2 s/rev) **plus** a static progress arc showing `step.index/step.total` in cyan underneath |
| `WAITING_FOR_USER` | amber, steady, 1.2 s slow blink |
| `COMPLETED` | green flash, 400 ms, then fade to cyan |
| `FAILED` | red flash ×2, then cyan |
| `CANCELLED` | grey flash, then cyan |
| `PANIC` | **red, 8 Hz strobe, full opacity, for 2 s**, avatar swapped to `avatar_dim` |
| `DEGRADED_*` | base ring colour at 50 % + the relevant button greyed/slashed |

Drive it from a single `QTimer` at 60 fps (8 ms in the sketch above is intentionally over-driven for smooth easing; 16 ms is fine). All animation is `QPainter` — no `QPropertyAnimation` on window attributes (that forces WM round-trips and stutters).

### 26.6 Optional expanded panel

`JARVIS_OVERLAY_PANEL=true` adds a slide-out 380 × 520 panel to the left of the orb containing the live task tree, tool trace, files changed, and a transcript — rendered either with `QPainter`/`QListWidget` (native, fast) or, for the exact Vice-cyberpunk look, by embedding the existing React build in a `QWebEngineView` **or** by opening a separate `pywebview` window pointed at `http://127.0.0.1:7860`. Prefer the separate pywebview window — no QtWebEngine dependency (it's ~150 MB), and it reuses work that already exists. Toggle with `Ctrl+Alt+Shift+P` or the context menu.

### 26.7 System tray

Also register a tray icon (`QSystemTrayIcon`) with the same menu, so the orb can be hidden entirely while Jarvis keeps running. Tray icon flashes red on panic, shows a badge with the active task count.

### 26.8 Console coexistence

The existing console I/O (`input()` prompt, printed transcripts) MUST keep working alongside the overlay. Move `input()` off `asyncio.to_thread` blocking and onto a `prompt_toolkit` async prompt if the overlay steals focus badly; otherwise keep it. Print all `[Audio]`/`[Screen]`/`[Camera]`/`[Bridge]`/`[State]` diagnostics to the console **and** surface user-relevant ones as overlay captions. The console is the debug surface; the overlay is the product surface. Both must be truthful.

---

## 27. FAILURE ISOLATION & RESILIENCE

### 27.1 The supervisor pattern (fix the `ExceptionGroup` problem for good)

The current code raises `asyncio.CancelledError` inside a `TaskGroup` body to stop everything. In 3.11+ that produces confusing `ExceptionGroup` wrapping and, on any real child failure, the user gets `unhandled errors in a TaskGroup (...)` with the actual cause buried. Replace with an explicit supervisor:

```python
class Supervisor:
    """Owns every subsystem task. One domain failing never takes down the others.
    Real exceptions are always printed in full. Shutdown is always clean."""

    DOMAINS = ("audio_in","audio_out","vision_screen","vision_camera","gemini",
               "bridge","router","narrator","state","overlay","console")

    async def run(self):
        results = {}
        tasks = {name: asyncio.create_task(self._guard(name, fn()), name=name)
                 for name, fn in self._enabled_subsystems()}
        try:
            while tasks:
                done, _ = await asyncio.wait(tasks.values(),
                                             return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    name = t.get_name()
                    exc = t.exception()
                    results[name] = "ok" if exc is None else f"{type(exc).__name__}: {exc}"
                    if exc is not None:
                        self._report(name, exc)              # ALWAYS print the real cause
                        await self._on_domain_death(name, exc)
                    del tasks[name]
                    if self._is_fatal(name):                 # only `gemini` is fatal
                        break
        finally:
            await self._shutdown(tasks, results)

    def _report(self, name, exc):
        print(f"\n{'='*64}\n [{name.upper()}] SUBSYSTEM FAILURE\n{'='*64}")
        if isinstance(exc, ExceptionGroup):                   # 3.11+: unwrap fully
            for i, sub in enumerate(exc.exceptions, 1):
                print(f" --- underlying error {i}/{len(exc.exceptions)} ---")
                traceback.print_exception(type(sub), sub, sub.__traceback__)
        else:
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        print('='*64, flush=True)
        # also push to the overlay caption + a red flash, and to a rotating
        # log file .kratos/omni-crash.log so it survives a closed terminal

    def _is_fatal(self, name): return name == "gemini"

    async def _on_domain_death(self, name, exc):
        """Degrade, don't die."""
        match name:
            case "audio_in":     self.capabilities.mic = False;  self.overlay.set_mic(False)
            case "audio_out":    self.capabilities.speaker = False
            case "vision_screen":self.capabilities.screen = False; self.overlay.set_screen(False)
            case "vision_camera":self.capabilities.camera = False; self.overlay.set_camera(False)
            case "bridge":       self.capabilities.kratos = False; self.state.force(DEGRADED_NO_KRATOS)
            case _:              pass
        if self._restartable(name):
            await asyncio.sleep(self._backoff(name))
            self._respawn(name)                              # supervised auto-restart, max 5 attempts
```

Rules:
- **Only `gemini` death is fatal** (there's no Jarvis without Gemini). Everything else degrades and, where sensible, auto-restarts with exponential backoff (1, 2, 4, 8, 16 s; max 5 attempts; then permanently degraded with a clear message).
- **Never** let an `ExceptionGroup` reach the shell unwrapped. Always print every underlying exception with its traceback.
- Install `sys.excepthook` and `loop.set_exception_handler` so stray exceptions in callbacks are also printed and logged, not swallowed.
- Handle `SIGINT`/`SIGTERM`/`SIGBREAK` (Windows) → graceful shutdown: release interlock, cancel tasks, stop streams, close session, `pya.terminate()`, join the Qt thread, print `[system] clean exit`.
- On any fatal exit, restore the user's environment: clipboard (if CCS touched it), foreground window, cursor position, input lock states, mic/camera off (release the devices so other apps can use them).

### 27.2 Kratos unavailable

Startup and mid-session. **Gemini conversation and vision MUST keep working.** Agent-task requests get a clear spoken explanation, never a crash, never a silent shutdown.

```
[JARVIS] starting
[JARVIS] Gemini Live ............ CONNECTED  (gemini-2.5-…-live · voice Zephyr)
[JARVIS] Kratos ................. CONNECTED  (sovereign · 115 tools · 2 displays · elevation ready)
[JARVIS] Audio in ................ READY      (Microphone Array (Realtek) @ 48000 → 16000)
[JARVIS] Audio out ............... READY      (Speakers (Realtek) @ 24000)
[JARVIS] Vision .................. READY      (screen: monitor 1 2560×1440 @1fps · camera: index 0)
[JARVIS] Overlay ................. READY      (PySide6 · frameless topmost · monitor 1)
[JARVIS] ready.
```

Degraded:
```
[JARVIS] starting
[JARVIS] Gemini Live ............ CONNECTED
[JARVIS] Kratos ................. UNAVAILABLE  (http://127.0.0.1:7860 refused connection)
[JARVIS]   → normal conversation and vision remain available
[JARVIS]   → agent tasks are disabled until Kratos responds
[JARVIS]   → start it with:  uv run kratos --web
[JARVIS] Audio in ................ READY
[JARVIS] Overlay ................. READY  (Kratos dot: red)
[JARVIS] ready (degraded — no execution backend).
```
And when the user then asks for a task, Jarvis *says*: *"I can't act right now — the execution backend isn't running. Start Kratos with `uv run kratos --web` and I'll pick it straight up. In the meantime, I can still talk and see."*

### 27.3 Gemini unavailable

- Retry the connection with exponential backoff (max 5), print the real error (auth vs. quota vs. network vs. unknown model), and if the API key is missing/invalid say so plainly and point at `.env`.
- If Gemini is permanently down, Omni **can still run Kratos** via typed console input: `message > fix the auth bug` routes through the intent classifier in fallback mode (§18.5, or a simple "everything typed is a task unless it starts with `?`") and narrates via **console text only** plus optional local TTS if `pyttsx3`/`piper` is installed. Voice is the preferred interface, not the only one.

### 27.4 Subsystem independence matrix

| Dies | Mic | Speaker | Screen | Camera | Gemini | Kratos | Overlay | Console |
|---|---|---|---|---|---|---|---|---|
| **Mic** | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (btn greyed) | ✓ |
| **Speaker** | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (text output) |
| **Screen** | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ (btn greyed) | ✓ |
| **Camera** | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ (btn greyed) | ✓ |
| **Gemini** | n/a | n/a | n/a | n/a | — | ✓ (typed console) | ✓ (degraded) | ✓ |
| **Kratos** | ✓ | ✓ | ✓ | ✓ | ✓ chat+vision | — | ✓ (dot red) | ✓ |
| **Overlay** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ |

Every cell marked ✓ MUST be verified by a test (§34.9).

---

## 28. SECURITY & SECRET HYGIENE

Not a guardrail on action — a guardrail on **leakage**. Kratos has full authority; it must not be a liability.

1. **Never** send to Gemini, never speak aloud, never write to any log, SSE event, audit record, snapshot, or D1 row: `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OMNI_KEY`, `BRAIN_KEY`, `DEEPSEEK_API_KEY`, `CLOUDFLARE_API_TOKEN`, `KRATOS_VOICE_TOKEN`, `AGENT_PASSWORD`, browser cookies, saved passwords, keychain/credential-store/DPAPI contents, SSH/OpenPGP private keys, `.env` file contents, OAuth tokens, session tokens, anything matching a secret regex.
2. **Redaction layer**, applied at four boundaries: (a) tool-result → event stream, (b) event → narration, (c) anything → audit log, (d) screen frame → Gemini (blur, §25.1). One shared implementation in `utils/redact.py`, used by both halves. Pattern set: the key-name regexes from §13.6 **plus** `AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{36}`, `xox[baprs]-…`, `sk-[A-Za-z0-9]{20,}`, `-----BEGIN .* PRIVATE KEY-----`, JWT `eyJ…\.eyJ…\.`, and high-entropy base64/hex ≥ 32 chars adjacent to a secret-ish key.
3. **Kratos MAY read and use secrets to accomplish a task** (e.g. read `.env` to configure a deployment). It just can't *emit* them.
4. **Never bypass Kratos's approval/capability machinery** — under `sovereign` it resolves to allow, but the code path still runs, still audits, still records. Removing the machinery would break the other three modes and destroy the audit trail.
5. **Bind the web server to `127.0.0.1`.** Verify in Phase 0. If it binds `0.0.0.0`, fix it. An agent with sovereign authority over the machine must not be drivable from the LAN. If remote access is genuinely wanted, it goes through an explicit tunnel the user sets up, documented, off by default.
6. **Elevated helper pipe**: DACL restricted to the current user SID, per-session random token from an inherited environment variable, never on disk, never logged, parent-pid watchdog.
7. **`.env` handling**: `load_dotenv()`, never commit. Create/update `.env.example` with **placeholders only**. Add `.env`, `.kratos/snapshots/`, `.kratos/audit/`, `.kratos/ccs/frames/`, `.kratos/ccs/browser-profile/`, `.kratos/voice_sessions.json`, `.kratos/overlay.json` to `.gitignore`. Verify none are already tracked; if they are, `git rm --cached` them and say so in the Final Report.
8. **No new env vars beyond what's actually needed.** Full list in §29. Every one appears in `.env.example` with a comment.
9. **CDP port** (`9222`) MUST bind to `127.0.0.1` only. Verify the launched browser's flags.
10. **Audit log is append-only** from the application's perspective: open with `O_APPEND`, never truncate in place, rotate by date.

---

## 29. CONFIGURATION

### 29.1 New environment variables

**Omni (`.env`, read by `config.py`):**

| Var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | *(required)* | Gemini auth |
| `GEMINI_LIVE_MODEL` | auto-discovered | Live model id |
| `JARVIS_VOICE` | `Zephyr` | Prebuilt voice name |
| `JARVIS_LANGUAGE` | `en-US` | Speech language |
| `JARVIS_MODE` | `jarvis` | `none`/`camera`/`screen`/`both`/`jarvis` |
| `JARVIS_SCREEN_FPS` | `1.0` | Screen capture rate |
| `JARVIS_CAMERA_FPS` | `1.0` | Camera rate |
| `JARVIS_MONITOR` | `1` | Screen capture monitor index |
| `JARVIS_CAMERA_INDEX` | `0` | Camera index |
| `JARVIS_CAPTURE_WINDOW` | *(unset)* | Window-title regex to scope screen capture |
| `JARVIS_SCREEN_REDACT` | `true` | Blur secret-looking screen regions |
| `JARVIS_MIC_DEVICE` | *(auto)* | Force an input device index |
| `JARVIS_MIC_GATE_DB` | `-52` | Noise gate threshold; `-99` disables |
| `JARVIS_SPEAKER_DEVICE` | *(auto)* | Force an output device index |
| `KRATOS_URL` | `http://127.0.0.1:7860` | Bridge base URL |
| `KRATOS_VOICE_TOKEN` | *(unset)* | Optional local bearer token |
| `JARVIS_BRIDGE_PROBE_S` | `10` | Health probe interval |
| `JARVIS_BRIDGE_MAX_RECONNECTS` | `12` | SSE reconnect budget |
| `JARVIS_BRIDGE_RESUME_ON_RECONNECT` | `true` | Resubmit in-flight task after Kratos restart |
| `JARVIS_SESSION_PERSIST` | `true` | Reuse the previous Omni session id |
| `JARVIS_RECALL_GREETING` | `true` | Offer to resume last work on launch |
| `JARVIS_NARRATE` | `true` | Speak progress |
| `JARVIS_NARRATE_MIN_INTERVAL` | `3.0` | Seconds between spoken progress lines |
| `JARVIS_NARRATE_COALESCE_MS` | `1200` | Coalescing window |
| `JARVIS_OVERLAY` | `true` | Show the floating overlay |
| `JARVIS_OVERLAY_BACKEND` | `auto` | `auto`/`pyside6`/`pywebview`/`tkinter`/`none` |
| `JARVIS_OVERLAY_POS` | *(unset)* | `"x,y"` override; else restored from `.kratos/overlay.json` |
| `JARVIS_OVERLAY_AUTOHIDE` | `true` | Fade during user activity |
| `JARVIS_OVERLAY_CAPTION` | `true` | Show the status strip |
| `JARVIS_OVERLAY_PANEL` | `false` | Show the expanded task panel |
| `JARVIS_OVERLAY_OPACITY` | `0.96` | Base opacity |
| `JARVIS_CTX_TRIGGER` / `JARVIS_CTX_TARGET` | `25600` / `12800` | Live context compression |
| `JARVIS_LOG_LEVEL` | `INFO` | Console verbosity |
| `JARVIS_TRANSCRIPT_LOG` | `true` | Write `.kratos/transcripts/{date}.jsonl` |

**Kratos (`.env`):**

| Var | Default | Purpose |
|---|---|---|
| `KRATOS_APPROVAL_MODE` | **`sovereign`** | Authority level |
| `KRATOS_PRESET` | `jarvis` | Harness preset |
| `KRATOS_WEB_HOST` | `127.0.0.1` | Bind address — MUST stay loopback |
| `KRATOS_WEB_PORT` | `7860` | Port |
| `KRATOS_VOICE_API` | `true` | Enable `/api/voice/*` |
| `CCS_ENABLED` | `true` | Load the Computer Control Subsystem |
| `CCS_INTERLOCK_ENABLED` | `true` | Human/agent input arbitration |
| `CCS_HUMAN_OVERRIDE_GRACE_MS` | `5000` | Yield duration after detecting user input |
| `CCS_INPUT_HUMANIZE` | `true` | Human-like timing/jitter |
| `CCS_PANIC_HOTKEY` | `ctrl+alt+shift+f12` | Global emergency stop |
| `CCS_PANIC_COOLDOWN_MS` | `1500` | Interlock lockout after panic |
| `CCS_AUTO_ELEVATE` | `true` | Spawn the elevated helper at startup |
| `CCS_ELEVATED_HELPER_IDLE_S` | `1800` | Helper self-exit idle timeout |
| `CCS_RESTORE_STATE` | `true` | Restore window/focus/cursor/clipboard after a task |
| `CCS_BROWSER_HEADLESS` | `false` | Keep the browser visible |
| `CCS_BROWSER_CDP_PORT` | `9222` | CDP port (loopback only) |
| `CCS_BROWSER_PROFILE_COPY` | `true` | Clone the user profile instead of touching it |
| `CCS_FRAMES_RETENTION` | `200` | Ring-buffer size for `.kratos/ccs/frames/` |
| `CCS_SNAPSHOT_RETENTION_MB` | `2048` | Snapshot budget |
| `CCS_SNAPSHOT_RETENTION_N` | `50` | Snapshot count budget |
| `CCS_AUDIT_RETENTION_DAYS` | `30` | Audit log retention |
| `CCS_OCR_ENGINE` | `auto` | `auto`/`rapidocr`/`tesseract`/`none` |
| `CCS_GROUNDING_VLM` | `auto` | Vision model for rung-8 grounding |
| `CCS_VLM_TIMEOUT_S` | `8` | Grounding call budget |
| `CCS_COMPUTER_TASK_MAX_STEPS` | `40` | Default step budget |
| `CCS_SUDO_ASKPASS` | *(unset)* | Linux elevation helper |

All existing Kratos vars (`CHAT_ENDPOINT`, `MODEL_ENDPOINT`, `OMNI_KEY`, `BRAIN_*`, `NORMAL_MODE_MODEL`, `OMNIROUTE_*`, `DEEPSEEK_API_KEY`, `AGENT_PASSWORD`, `CLOUDFLARE_*`, `KRATOS_D1_LOCAL_MIRROR`, `HEADROOM_*`, `KRATOS_PARALLEL_EXECUTION`, `KRATOS_MAX_PARALLEL_WORKERS`) stay exactly as they are.

### 29.2 CLI surface

```bash
# OMNI
python live.py                                  # == --mode jarvis (default)
python live.py --mode jarvis|both|screen|camera|none
python live.py --monitor 2 --camera-index 1
python live.py --capture-window "Chrome"
python live.py --no-overlay                     # console only
python live.py --kratos-url http://127.0.0.1:8080
python live.py --voice Puck --language en-GB
python live.py --quiet                          # narration: errors + results only
python -m omni.audio --list-devices             # device diagnostic table
python -m omni.vision --list-monitors --list-cameras

# KRATOS
uv run kratos --web                             # brain + voice API (default sovereign)
uv run kratos --web 8080
uv run kratos --cli
uv run kratos "<one-shot prompt>"
uv run kratos --mode sovereign|full-auto|auto-edit|suggest
uv run kratos --no-ccs                          # disable computer control
uv run kratos --elevate                         # start already elevated
uv run python -m kratos_agent.ccs.doctor        # CCS capability self-test
```

`ccs.doctor` is a **required deliverable**: probes every backend, prints the capability table, runs a harmless live test of each channel (screenshot, OCR, a11y dump, a 1 px mouse move and back, a keystroke into a scratch notepad/`xdotool` target, window list, display info, elevation availability), and reports pass/fail per capability with the fix for each failure. This is how the user — and you — verify CCS actually works on this machine.

---

## 30. MODULE & FILE PLAN

**Only create what's needed. Resist scaffolding "just in case."**

### 30.1 Omni (new package layout)

```
omni/                                  # or keep flat if the workspace is flat — match existing style
├── live.py                            # MODIFIED IN PLACE — thin entry: arg parse, config, Supervisor.run()
├── config.py                          # NEW — env resolution, dataclasses, validation, one place for defaults
├── supervisor.py                      # NEW — §27.1
├── audio.py                           # NEW — backends, device enum, native-rate capture, resample, playback, barge-in
├── vision.py                          # NEW — mss screen (DPI-aware, monitor/window scoped, redaction), cv2 camera
├── gemini_client.py                   # NEW — session config build, model discovery, receive loop, fn-call dispatch, injection
├── intent_router.py                   # NEW — function declarations, arg validation, dispatch, fallback classifier
├── agent_bridge.py                    # NEW — KratosBridge (§19)
├── event_adapter.py                   # NEW — SSE parse → AgentEvent (§16.3)
├── narrator.py                        # NEW — dictionary + throttle + coalesce + sanitize + LLM final summary (§20)
├── task_state.py                      # NEW — state machine + session registry + task queue (§21, §23)
├── prompts/
│   ├── jarvis_system.py               # NEW — the persona/routing/narration system prompt (§17.3)
│   └── narration.py                   # NEW — result-summarization instruction templates
├── overlay/
│   ├── __init__.py
│   ├── jarvis_overlay.py              # NEW — OverlayController + Qt thread (§26.2)
│   ├── widget.py                      # NEW — JarvisWidget: avatar, ring, caption, buttons, menu, drag, snap
│   ├── buttons.py                     # NEW — NeonButton (mic / screen / camera / stop)
│   ├── ring.py                        # NEW — QPainter state-ring painter, per-state animation
│   ├── tray.py                        # NEW — QSystemTrayIcon
│   ├── build_assets.py                # NEW — derive orb/ring/icons from kratos-illu.png
│   ├── webview_overlay.py             # NEW — pywebview fallback
│   ├── tk_overlay.py                  # NEW — tkinter fallback
│   └── hotkeys.py                     # NEW — global hotkey registration (panic + button equivalents)
└── assets/jarvis/
    ├── kratos-illu.png                # CANONICAL avatar path (see §26.1)
    └── icons/*.svg|png
```

### 30.2 Kratos (deltas)

```
MODIFIED  src/kratos_agent/core/approval_mode.py       # + SOVEREIGN, + capability tags, gate short-circuit
MODIFIED  src/kratos_agent/core/tool_runtime.py        # + tag plumbing, path-policy switch, _forbidden_target,
                                                       #   wave-group classification for CCS tools
MODIFIED  src/kratos_agent/core/runtime_contracts.py   # + EventKind members (PANIC, CAPABILITY, GUI_STEP,
                                                       #   ELEVATION, INTERLOCK), + narratable/narration/frame_ref
MODIFIED  src/kratos_agent/core/harness/presets.py     # + `jarvis` preset
MODIFIED  src/kratos_agent/core/context_pipeline.py    # + image/* guard (skip Headroom, downscale instead)
MODIFIED  src/kratos_agent/core/agent_loop.py          # + steering-message injection point (§22.2)
MODIFIED  src/kratos_agent/web/server.py               # + /api/voice/* routes, SSE, panic, health, capabilities
MODIFIED  src/kratos_agent/main.py                     # + probe_capabilities(), sovereign default, CCS wiring
MODIFIED  src/kratos_agent/cli.py                      # + /mode sovereign, /audit, /persist, /ccs, /panic
MODIFIED  src/kratos_agent/utils/tools_list.json       # + ~90 CCS tool schemas
MODIFIED  src/kratos_agent/utils/tools.py              # + CCS tool dispatch shims (or a ccs_tools.py imported by it)
MODIFIED  src/kratos_agent/core/background_runner.py   # + voice-task integration if not already suitable
MODIFIED  pyproject.toml                               # + extras (§14.3), + ccs/overlay/voice entry points
MODIFIED  .env.example                                 # + every var from §29
MODIFIED  .gitignore                                   # + .kratos/snapshots|audit|ccs/frames|ccs/browser-profile,
                                                       #   .env, overlay.json, voice_sessions.json, transcripts
MODIFIED  README.md                                    # §37
NEW       src/kratos_agent/ccs/**                      # §7.1 (whole tree)
NEW       src/kratos_agent/utils/redact.py             # shared secret redaction (§28.2)
NEW       src/kratos_agent/core/audit_trail.py         # §13.6
NEW       src/kratos_agent/core/snapshots.py           # §13.5  (or inside ccs/safety_ops.py)
NEW       tests/test_ccs_*.py, tests/test_voice_api.py, tests/test_sovereign_mode.py,
          tests/test_input_interlock.py, tests/test_panic.py, tests/test_undo_snapshots.py,
          tests/test_audit_redaction.py
NEW       docs/jarvis.md, docs/computer-control.md, docs/sovereign-mode.md, docs/voice-api.md
NEW       DISCOVERY.md                                 # Phase 0 output
NEW       JARVIS-SOVEREIGN-SPEC.md                     # this document, committed
```

---

## 31. STARTUP & RUNTIME BEHAVIOR

### 31.1 Two terminals

```bash
# Terminal 1 — the brain
uv sync --extra all          # first time
uv run kratos --web          # sovereign by default; serves http://127.0.0.1:7860

# Terminal 2 — the senses and the face
python live.py               # == --mode jarvis
```

Confirm the **actual** Kratos start command from the workspace (Phase 0). Do not assume `uv run kratos --web`.

### 31.2 Omni boot sequence

```
 1. parse args → resolve config → validate (fail fast with a clear message on a bad value)
 2. load_dotenv(); assert GEMINI_API_KEY present, else print the exact .env line to add and exit 2
 3. print the JARVIS banner (ASCII, Vice-cyberpunk, model + mode + version)
 4. start the overlay EARLY (it's the user's only feedback surface) in its own thread,
    state = BOOTING (ring: white sweep)
 5. audio: enumerate devices → select → validate rates → open output first (speaker is
    less likely to fail and gives immediate feedback) → open input
    overlay buttons reflect real availability at each step
 6. vision: set DPI awareness → probe monitors → probe cameras → report both
 7. bridge: health_check() (3 s timeout) → capabilities() → ensure_session()
    overlay Kratos dot green/red/amber
 8. gemini: discover live model → build config with function_declarations → connect
    overlay state = CONNECTING (ring: violet)
 9. register global hotkeys (panic + mic/screen/camera/panel/click-through)
10. spawn the Supervisor with every enabled domain
11. print the [JARVIS] status block (§27.2)
12. overlay state = IDLE
13. optional recall greeting (§23.3)
```

Every step MUST be independently failable with a printed reason and a degraded continuation (except steps 2 and 8, which are fatal).

### 31.3 Kratos boot additions

```
…existing boot…
 → harness kernel starts the `jarvis` preset
 → CCSHarnessPlugin.start(): probe backends, register ~90 tools, publish ccs:ready
 → if CCS_AUTO_ELEVATE: spawn the elevated helper (ONE UAC prompt for the whole session)
 → register the panic hotkey (in the helper if elevated, else in-process)
 → start the input interlock poller
 → probe_capabilities() → cache
 → web server: mount /api/voice/*, log the route table
 → print:
   [KRATOS] mode: SOVEREIGN — full authority, no prompts
   [KRATOS] CCS: 87/91 capabilities online · elevation ready · 2 displays · chrome(cdp)
   [KRATOS] CCS missing: touch input, elevated-window injection (helper not spawned)
   [KRATOS] voice API: http://127.0.0.1:7860/api/voice/health
   [KRATOS] panic hotkey: Ctrl+Alt+Shift+F12
```

---

## 32. TESTING

### 32.1 Baseline discipline

**Before any change:** run the full Kratos suite, record the exact result in `DISCOVERY.md`.
```bash
uv run python -m unittest discover tests -v 2>&1 | tee /tmp/kratos-baseline.txt
```
**After all changes:** run it again. **Same or better. Any regression is a failed delivery.** Known-relevant: `test_runtime.py`, `test_stream_response.py`, `test_web_live_chat.py`, `test_agent_execution_ux.py`, plus everything else present.

**Do not duplicate Kratos's own coverage inside Omni's suite.** Omni tests the bridge and the voice layer. Kratos tests CCS and the voice API. No overlap.

### 32.2 Omni tests (`tests/omni/` or `omni/tests/`, `pytest` + `pytest-asyncio`)

| # | Area | Cases |
|---|---|---|
| T1 | Intent routing (fn-call path) | Every §18.3 calibration line classifies correctly. Assert the exact function name and that `task_description` is fully resolved (no dangling "this"/"that"/"the first one"). ≥ 90 % accuracy on the combined set. |
| T2 | Intent routing ambiguity | Genuinely ambiguous input → exactly one clarifying question, no tool call. |
| T3 | Routing edge cases | Stop phrase while `EXECUTING` → `PANIC_NOW`, no question. "also fix the lint" while `EXECUTING` → `STEER`. Vision-only question → `ANSWER_DIRECTLY(used_vision=true)`. Vision + action verb → `START_AGENT_TASK` with non-empty `visual_context`. |
| T4 | Bridge: happy path | Mock Kratos (a local `http.server` fixture). `health_check`, `ensure_session` (idempotency: same id twice → same kratos id), `submit_task` returns a task id in < 200 ms, `status`, `cancel`, `steer`, `undo`, `panic`, `list_tasks`, `capabilities`. |
| T5 | Bridge: SSE parsing | Multi-line `data:`, `id:` monotonic, `event:` types, `:` comment heartbeats, partial chunks split across TCP reads, CRLF vs LF, UTF-8 multibyte split across a chunk boundary, malformed JSON line (skip + log, don't crash). |
| T6 | Bridge: reconnection | Kill the mock server mid-stream → backoff sequence 0.5/1/2/4/8 → `Last-Event-ID` sent on reconnect → no duplicate and no missing events → synthetic `warning` event yielded → after max retries, a terminal `error` event. |
| T7 | Bridge: Kratos down | `submit_task` raises `BridgeUnavailable`; conversation and vision mocks keep working; the spoken unavailability message is produced; no crash; the health watcher flips `available` and the overlay dot. |
| T8 | Event adapter | Every real SSE sample from `DISCOVERY.md` maps to a correct `AgentEvent`. Unknown `type` → `log` event, `narratable=False`, no crash. Missing optional fields → defaults. |
| T9 | Narrator dictionary | Each row of the §20.2 table produces a line ≤ 220 chars, no `{`, no `traceback`, no path longer than a basename. |
| T10 | Narrator throttle | 200 events in 5 s → ≤ 3 spoken lines. Priority ordering respected (an `error` in the window always wins). Identical consecutive lines deduped. Queue cap 3, drop-oldest. |
| T11 | Narrator sanitize | Feed it a stack trace, a JSON blob, a 4 KB diff, a string containing `sk-…`, a URL with a token → all rejected or redacted. **This test is a hard gate.** |
| T12 | Narrator final result | §20.2's sample payload → one sentence, no field names, no full paths, spoken-form numbers. |
| T13 | State machine | Every legal transition fires; every illegal transition is rejected and logged; concurrent `barge-in` + `terminal event` → deterministic outcome (lock holds); terminal → `IDLE` after narration + 800 ms. |
| T14 | Session continuity | Two `submit_task` calls in one run share one `kratos_session_id`; the mapping survives an Omni restart within 24 h (`voice_sessions.json`); `previous_task_id` is passed on the second. |
| T15 | Concurrency | New task while `EXECUTING` → one question, then cancel-and-replace **or** queue per the answer; queue auto-submits on the terminal event; no-answer-in-30 s → queued + announced; stop phrase pre-empts with no question. |
| T16 | Audio: discovery | Fake device tables → correct ranking (OS default > WASAPI > CoreAudio > ALSA > MME). Empty table → the exact §24.2 Cause-1 message. Stale default (raises) → falls through to candidates. |
| T17 | Audio: rate validation | Device supporting only 44100 → captures at 44100, resamples to 16000. Device supporting nothing → Cause-3 message. `-9999` on open → Cause-ranked message + one retry on the next candidate. |
| T18 | Audio: resampling | 48000→16000 and 44100→16000 round-trip a 1 kHz sine: output frequency within ±2 %, no DC offset drift, no boundary clicks (max inter-chunk sample delta bounded), length ratio exact. |
| T19 | Audio: barge-in | Inject 50 chunks, fire `interrupted` → queue depth 0 within one write cycle; `narrator.cancel_pending()` called; state → `LISTENING`. |
| T20 | Audio: mute | Mute → nothing enqueued for 2 s of simulated capture; unmute → resumes; overlay button state matches. |
| T21 | Vision: screen | Fake `mss` → correct monitor selection, region crop, downscale to ≤ 1568, JPEG q78, 1 fps cadence ±20 %, drop-oldest under backpressure. Capture exception → backoff to 0.2 fps, no crash, `vision_degraded`. |
| T22 | Vision: redaction | A frame containing `export GEMINI_API_KEY=sk-…` → the region is blurred in the output; the log records "1 region blurred" and **not** the value. |
| T23 | Vision: camera | Fake `cv2.VideoCapture`: index 0 fails / index 1 works → selects 1. All fail → clear reason, camera disabled, everything else runs. First 4 frames discarded. |
| T24 | Vision: modes | `--mode none/camera/screen/both/jarvis` each spawn exactly the expected task set. |
| T25 | Gemini client | Fake session: `function_call` → correct handler → `function_response` sent with the right name and payload; malformed args → defaults, no crash; duplicate call for the same transcript hash → idempotent; 5 s watchdog fires when the handler hangs. |
| T26 | Progress injection | Injection only when `IDLE`; queued and coalesced otherwise; ≤ 1 per 3 s; never during `LISTENING`; marker present so the transcript hides it. |
| T27 | Supervisor / isolation | Kill each domain one at a time (11 domains × 1) → every other domain survives; the real exception is printed in full; `ExceptionGroup` is unwrapped; restartable domains respawn with correct backoff; only `gemini` death exits. Verify the §27.4 matrix cell by cell. |
| T28 | Panic | Voice stop, hotkey, and API each → interlock `PANIC`, `input_release_all` called, all tasks cancelled, spawned pids terminated, overlay strobe, "Stopped." spoken, Kratos server and Omni still alive, interlock `FREE` after cooldown. |
| T29 | Overlay | Headless-safe (`QT_QPA_PLATFORM=offscreen`): widget constructs; each `set_*` command applies; button click emits the right outbound event; state → ring config mapping is total (every `State` has a config); collapse/expand; position persist + restore; click-through toggles the attribute; disabled buttons carry the real reason string. |
| T30 | Shutdown | SIGINT/SIGTERM → clean exit code 0, streams closed, `pya.terminate()` called, Qt thread joined, devices released, no dangling tasks, `[system] clean exit` printed. |

### 32.3 Kratos tests (`tests/`)

| # | Area | Cases |
|---|---|---|
| K-T1 | `test_sovereign_mode.py` | Enum has 4 members; `resolve()` returns `allow=True, needs_confirmation=False` for **every** capability tag under `sovereign`; the other three modes are byte-for-byte unchanged in behaviour; env default is `sovereign`; `/mode sovereign` parses; audit record written on every allow. |
| K-T2 | `test_voice_api.py` | Every §15.2 route: status code, content type, body schema. `POST /task` returns 202 in < 200 ms with a live runtime (does not block). SSE emits `id`/`event`/`data`, heartbeats every ~15 s, `event: done` after a terminal status. `Last-Event-ID` resume yields no gaps and no dupes. Subscriber disconnect does **not** cancel the task. Errors return JSON, never an HTML traceback. Bind address is `127.0.0.1`. |
| K-T3 | `test_ccs_perception.py` | Backend selection per platform; screenshot returns valid PNG/JPEG with correct dimensions; DPI-awareness call recorded; OCR returns text + boxes; a11y dump respects `max_depth`/`max_nodes`/`visible_only`; every unimplemented method raises `CapabilityUnavailable` **with a non-empty `hint`**. Uses fakes — no real screen needed in CI. |
| K-T4 | `test_ccs_grounding.py` | The 9-rung ladder: inject a hit at each rung, assert it stops there and reports `method`. Cache hit on repeat `(frame_hash, query)`. Rung 9 returns `{ok:false, tried:[1..8]}`. |
| K-T5 | `test_input_interlock.py` | Acquire/release; single-flight (second acquire blocks or fails); simulated physical input during `AGENT` → `HUMAN_OVERRIDE` within one poll; `input_release_all` called on every yield/panic/error/shutdown; grace period respected; re-acquire after grace. |
| K-T6 | `test_panic.py` | `panic()` performs steps 1–9 of §13.1 in order (mocked), completes in < 50 ms of *handler* time, cancels only the target task with `scope=task`, leaves the server and other tasks alive, writes an audit record. |
| K-T7 | `test_ccs_wave_groups.py` | Every CCS tool is in exactly one wave group. All input/GUI-mutating tools are in the single-flight group. All perception tools are in the concurrent read group. `tool_call_id` order is preserved in the assembled history even when reads complete out of order. |
| K-T8 | `test_undo_snapshots.py` | `write_file` outside git → pre-image snapshot; inside git → `git stash create` SHA recorded; `registry_write` → `.reg` export; `undo_last_operation` restores in reverse order; retention evicts by count and by MB; content-addressing dedupes identical bytes. |
| K-T9 | `test_audit_redaction.py` | Feed every secret pattern from §28.2 → redacted to `«REDACTED:sha8»`. Non-secret values pass through unchanged. Audit file is append-only. **Hard gate.** |
| K-T10 | `test_forbidden_targets.py` | Each §13.2 invariant blocks; the `FAILED` event names the invariant; everything *near* the invariant (a normal file in `C:\Users\…`, a normal service restart, a normal `system_power restart` the user asked for) is **allowed**. Assert both directions — over-blocking is a bug too. |
| K-T11 | `test_elevation.py` | `can_elevate()` truthfulness; helper spawn/pipe/token/parent-watchdog; UIPI detection reports `input_can_reach_elevated_windows=false` when unelevated; secure-desktop detection emits `WAITING_FOR_USER` and resumes after. |
| K-T12 | `test_ccs_browser.py` | CDP attach + fallback path selection; profile copy (never writes to the real profile dir); `browser_read mode=markdown` strips boilerplate and passes through Headroom; dialog detection. |
| K-T13 | `test_ccs_tools_registry.py` | Every tool in `tools_list.json` has an implementation and vice versa; every schema validates; every tool declares ≥ 1 capability tag; no name collisions with the existing 24; the count matches what `probe_capabilities` reports. |
| K-T14 | `test_steering.py` | `POST /steer` mid-task → message appears in the next model context; planner emits `plan` with `revised:true`; the task id is unchanged; no restart. |
| K-T15 | `test_headroom_image_guard.py` | An `image/*` tool result is **not** sent to Headroom; it is downscaled instead; text results still compress; stats still account correctly. |
| K-T16 | Regression | The entire pre-existing suite, unmodified, green. |

### 32.4 CI note

CCS tests MUST run against fakes/backends-stubbed so they pass on a headless CI runner. Mark the handful that genuinely need a display with `@pytest.mark.requires_display` and skip them when no display is present. **A test suite that can't run headless is a test suite that doesn't run.**

---

## 33. MANUAL END-TO-END SCRIPT

Run in order. Record pass/fail for each line in the Final Report. Use headphones.

### 33.1 Boot matrix

```
[ ] uv run kratos --web                        → banner shows SOVEREIGN, CCS caps table, voice API URL
[ ] python -m kratos_agent.ccs.doctor          → all capabilities probed, failures explained
[ ] python live.py --mode none                 → clean boot, overlay up, mic+speaker live, Kratos dot green
[ ] python live.py --mode camera               → + camera live, button green
[ ] python live.py --mode screen               → + screen live, button cyan
[ ] python live.py --mode both                 → + both live simultaneously
[ ] python live.py                             → defaults to jarvis mode, identical to --mode jarvis
[ ] python live.py --no-overlay                → console-only, all functionality intact
```

### 33.2 Conversation & vision (no Kratos involvement)

```
[ ] "Hello."                                   → warm short reply, no tool call, no Kratos event
[ ] "What is RAG?"                             → substantive spoken answer, ANSWER_DIRECTLY logged
[ ] "What do you see on my screen?"            → accurate description of the visible content, used_vision=true
[ ] "Read that error out loud."                → reads it, does NOT fix it
[ ] "What can you do?"                         → answer generated from /api/voice/capabilities, not hardcoded
[ ] "Are you admin?"                           → truthful, from the capability probe
[ ] Interrupt mid-answer by speaking            → audio stops within ~100 ms, Jarvis listens, answers the new thing
```

### 33.3 Agent tasks — code

```
[ ] "Inspect this project."                    → plan event, throttled narration, files read, spoken summary
[ ] "Find the error and fix it."               → edits, snapshot taken, verification runs, result spoken in one sentence
[ ] "Run the tests."                           → terminal runs, results narrated, pass/fail spoken
[ ] "Run the tests and fix whatever fails."    → full loop: run → diagnose → fix → re-run → verify → report
[ ] "Undo that."                               → UNDO_LAST, files restored, spoken confirmation, `git status` clean
[ ] "Refactor the auth module and add tests."  → parallel subagents fire, wave scheduler visible in /audit
[ ] "What did you just do?"                    → spoken summary sourced from GET /api/voice/audit
```

### 33.4 Agent tasks — the whole computer (Sovereign)

```
[ ] "Open Chrome."                             → a real, visible Chrome window opens
[ ] "Go to LinkedIn and find remote Python jobs in Berlin from the last day."
                                               → visible browser driving; CDP or UIA fallback; results spoken
[ ] "Save the interesting ones to a spreadsheet."
                                               → creates/writes a real file; path spoken
[ ] "Open Notepad and type a shopping list."   → input injection into a real app, text appears, verified by a11y
[ ] "Take a screenshot and put it on my desktop."
[ ] "What's eating my CPU? Kill it."           → process list → terminate tree → confirmation
[ ] "Install ripgrep."                         → package manager detected, installed, verified, no prompt
[ ] "Set a dark theme."                        → OS settings driven via UI automation or deep link
[ ] "Turn the volume down to 20."
[ ] "Lock the screen in ten seconds."          → warns, then does it
[ ] "Make this repo run every morning at nine."→ scheduled task created, listed by "what runs automatically?"
[ ] "Restart the print spooler."               → ELEVATES ITSELF. One UAC prompt at most (at startup). No voice question.
[ ] "Open the registry editor and show me HKCU\Environment."
[ ] A task needing an elevated window          → helper handles it, or a precise CapabilityUnavailable is spoken
[ ] Windows secure-desktop UAC prompt          → WAITING_FOR_USER event → "please tap Yes" → auto-resumes
```

### 33.5 Control

```
[ ] During a long task: "Stop."                → interlock released, all injection stops <50 ms, task cancelled,
                                                  "Stopped." spoken, overlay strobes red, Kratos server still up
[ ] Ctrl+Alt+Shift+F12 during injection        → identical result, works even if Omni is unresponsive
[ ] Physically type during agent injection     → Jarvis yields within ~100 ms, says "I felt you typing — pausing",
                                                  resumes after 5 s of no input, no corrupted keystrokes either way
[ ] "How's it going?" mid-task                 → current step, progress, elapsed, files touched
[ ] "Actually, use PostgreSQL instead."        → STEER, task continues with the new goal, plan revised event
[ ] While executing: "Also clean up the README."→ one question, then queue-or-replace per the answer
[ ] While executing: "Cancel and do this instead"→ immediate, no question
[ ] Overlay: click mic                         → capture actually stops; Gemini hears nothing; icon slashed
[ ] Overlay: click screen                      → screen task actually stops/starts; icon reflects truth
[ ] Overlay: click camera                      → same; privacy LED follows the real state
[ ] Overlay: drag / double-click / right-click → moves+persists / collapses to orb / full menu
[ ] Overlay: middle-click                      → click-through on; Ctrl+Alt+Shift+F9 exits it
[ ] Overlay: stop button during EXECUTING      → same as voice stop
```

### 33.6 Resilience

```
[ ] Kill Kratos mid-task                       → red dot, spoken "I've lost contact with the execution backend",
                                                  chat + vision still work perfectly
[ ] Then ask "Fix the bug"                     → clear spoken unavailability, start command mentioned, NO CRASH
[ ] Then ask "What do you see?"                → answers normally
[ ] Restart Kratos                             → green dot, "Kratos is back", in-flight task resumed if configured
[ ] Unplug the microphone mid-session          → clean diagnostic, mic button greyed with the real reason,
                                                  typing in the console still drives everything
[ ] Unplug a monitor mid-session               → screen capture backs off, no crash, topology re-probed
[ ] Close the laptop lid / lock the workstation → capture degrades gracefully, resumes on unlock
[ ] Ctrl+C in the Omni terminal                → clean exit 0, devices released, Qt thread joined, interlock released,
                                                  clipboard/cursor/foreground window restored
[ ] Ctrl+C in the Kratos terminal              → clean exit, elevated helper self-terminates, hotkey unregistered
[ ] Pull the network                           → bridge backoff sequence visible, chat degrades gracefully,
                                                  no exception reaches the shell
[ ] Set a bad GEMINI_API_KEY                   → precise auth error naming the variable, exit code 2, no traceback spam
```

---

## 34. ACCEPTANCE CHECKLIST

Every box MUST be checked in the Final Report, with evidence.

**Authority**
- [ ] `sovereign` is the default mode; the banner and status bar say so
- [ ] No approval prompt of any kind fires during the entire §33 run — no CLI y/N, no modal, no voice confirmation, no HTTP `WAITING_FOR_CONFIRMATION`
- [ ] Kratos self-elevates when a task needs admin; at most one UAC prompt per session, at startup
- [ ] Keyboard, mouse, window, display, app, browser, registry, service, scheduler, power, volume, network, install, and filesystem operations all succeed outside the workspace
- [ ] `probe_capabilities()` reports the truth and the spoken answer to "what can you do?" is generated from it
- [ ] The three modes `suggest` / `auto-edit` / `full-auto` still work exactly as before

**Control & recoverability**
- [ ] Voice stop and the global hotkey both halt all injection in < 50 ms and cancel only the target task
- [ ] Physical user input during injection yields within one poll interval and resumes after the grace period, with no corrupted keystrokes
- [ ] No stuck modifier or held mouse button survives a panic, an error, or a shutdown
- [ ] Snapshots are taken for every mutating operation; `undo_last_operation` demonstrably restores them
- [ ] The audit log records every mutating action, append-only, with all secrets redacted
- [ ] All eight §13.2 self-preservation invariants hold, and nothing else is blocked

**Voice & vision**
- [ ] Normal chat works with Kratos up **and** down
- [ ] Screen vision works without Kratos; camera works without Kratos
- [ ] All five modes boot clean: `none` / `camera` / `screen` / `both` / `jarvis`
- [ ] Barge-in flushes playback within ~100 ms and re-routes the new utterance correctly
- [ ] Mic failure produces the ranked diagnostic, never a bare traceback; the app keeps running without a mic
- [ ] Native-rate capture + resample to 16 kHz is verified by a frequency-accuracy test
- [ ] No raw screen or camera frame ever crosses the bridge — only `visual_context` text

**Brain & bridge**
- [ ] Agent tasks reach Kratos with the **full resolved** task description, never a bare label
- [ ] Kratos events are consumed via the real, discovered SSE contract with working `Last-Event-ID` resume
- [ ] Narration is throttled (≤ 1 line / 3 s), coalesced, ≤ 220 chars, and contains no JSON, no field names, no chain-of-thought, no stack traces, no secrets
- [ ] The final result is spoken as natural sentences, never read as JSON
- [ ] Cancellation kills exactly one task; the Kratos server and Omni both stay up
- [ ] Steering changes a running task's goal without restarting it
- [ ] One Omni run = one Kratos session; "fix the first issue" resolves correctly across turns
- [ ] A new task during `EXECUTING` produces exactly one question, then queues or replaces per the answer

**Overlay**
- [ ] `kratos-illu.png` renders as a circular orb, HiDPI-crisp, with the animated state ring
- [ ] Mic, screen, and camera buttons sit **below** the image, exactly as specified
- [ ] Each button's visual state matches the real subsystem state at all times — never a lie
- [ ] Disabled buttons carry the actual diagnostic reason in the tooltip
- [ ] Drag, edge-snap, position persistence, collapse-to-orb, click-through, context menu, tray icon, auto-hide all work
- [ ] The ring renders a distinct, correct animation for all 12 states
- [ ] The overlay runs on its own thread; the asyncio loop never blocks on Qt; no cross-thread widget access

**Isolation & quality**
- [ ] The §27.4 matrix holds: killing any one domain leaves all others working (tested, not assumed)
- [ ] No `ExceptionGroup` ever reaches the shell; every real exception is printed with its traceback and logged
- [ ] Graceful shutdown on SIGINT/SIGTERM restores clipboard, cursor, foreground window, input locks, and releases all devices
- [ ] The web server binds `127.0.0.1`; the CDP port binds `127.0.0.1`
- [ ] No secret appears in any log, SSE frame, audit record, snapshot, or spoken output (grep-verified)
- [ ] `.gitignore` covers every new runtime artifact; nothing secret is staged
- [ ] **The entire pre-existing Kratos test suite passes, unmodified**
- [ ] Every new test module in §32 exists and passes, including headless-skippable CCS tests
- [ ] `DISCOVERY.md` exists, is complete, and lists every divergence and every blocker

---

## 35. ANTI-PATTERNS — HARD PROHIBITIONS

Violating any of these is a failed delivery.

1. **MUST NOT** clone, fetch, submodule, or download any external repository. The workspace is everything.
2. **MUST NOT** invent an endpoint, event name, SSE field, class, method signature, enum member, tool name, or config key. If Phase 0 didn't find it, it doesn't exist — go find the real thing or build it explicitly and document it.
3. **MUST NOT** rebuild Kratos inside Omni. No second planner, no second agent loop, no second tool registry, no second memory store, no second task manager, no second event system. Omni calls Kratos.
4. **MUST NOT** duplicate Kratos's own test coverage inside Omni's suite.
5. **MUST NOT** construct a second `KratosRuntime`. One process, one runtime, one memory.
6. **MUST NOT** let an `ExceptionGroup` reach the shell unwrapped.
7. **MUST NOT** silently swallow an exception. Every `except` either handles it visibly or re-raises.
8. **MUST NOT** leak a secret or Kratos's chain-of-thought to Gemini, to speech, to a log, to SSE, to the audit trail, or to a snapshot.
9. **MUST NOT** add an approval prompt, confirmation dialog, "are you sure", y/N, or timeout-then-ask anywhere. `sovereign` means sovereign.
10. **MUST NOT** remove or weaken the other three approval modes.
11. **MUST NOT** stream raw screen or camera frames to Kratos. Only Gemini's natural-language summary crosses.
12. **MUST NOT** parallelize input injection. Single-flight, interlock-guarded, always.
13. **MUST NOT** inject a held key or mouse button and fail to release it on any exit path — including panics, exceptions, and SIGKILL-adjacent shutdowns.
14. **MUST NOT** kill the Omni process, the Kratos server, or the hosting terminal to cancel a task.
15. **MUST NOT** write into the user's real browser profile directory. Copy it.
16. **MUST NOT** bind the web server or the CDP port to anything but loopback.
17. **MUST NOT** downgrade Kratos to 3.13 or upgrade Omni to 3.14 without the verification in §14.1.
18. **MUST NOT** break the existing Kratos test suite.
19. **MUST NOT** call `mss.MSS()` — the maintained entry point is `mss.mss()`. Verify against the pinned version.
20. **MUST NOT** assume `audioop` exists on Python 3.13. It does not.
21. **MUST NOT** touch a QWidget from the asyncio thread.
22. **MUST NOT** call UIA/AX COM objects from arbitrary threads — one dedicated apartment thread.
23. **MUST NOT** let an overlay button show a state that differs from the real subsystem state.
24. **MUST NOT** scaffold modules "just in case". Build what §30 lists.
25. **MUST NOT** narrate every event. Roughly one in eight, throttled to one per three seconds.
26. **MUST NOT** read JSON, field names, stack traces, or full file paths aloud.
27. **MUST NOT** silently drop or silently queue a task request that arrives mid-execution. Ask once.
28. **MUST NOT** guess the Gemini live model id. Discover it, or take it from env, or fail loudly with the candidate list.
29. **MUST NOT** hardcode the answer to "what can you do?" — generate it from `probe_capabilities()`.
30. **MUST NOT** treat an OS trust boundary (UAC secure desktop, macOS Accessibility/Screen Recording, Wayland input restrictions) as a bug to route around. Detect it, report it precisely, narrate the exact fix, and resume automatically once it clears.

---

## 36. EXECUTION PHASES — WORK ORDER

Do them in order. Do not skip Phase 0. Commit after each phase with a message naming the phase.

| # | Phase | Deliverable | Gate to proceed |
|---|---|---|---|
| **0** | **Discovery** (§5) | `DISCOVERY.md`, complete, with the Kratos test baseline recorded | Note exists. Every matrix row resolved. Blockers listed. |
| **1** | Topology decision (§14.1) | Recorded decision: two-process vs in-process, with proof | Decision + evidence in `DISCOVERY.md` |
| **2** | Sovereign mode (§6) | `approval_mode.py`, capability tags, gate short-circuit, default flip, `probe_capabilities()` | `test_sovereign_mode.py` green; existing suite still green |
| **3** | Safety ops (§13) | Interlock, panic, snapshots, undo, audit trail, redaction, forbidden targets | `test_input_interlock`, `test_panic`, `test_undo_snapshots`, `test_audit_redaction`, `test_forbidden_targets` green |
| **4** | CCS foundations (§7) | `ccs/` tree, `base.py`, `registry.py`, backend for the host platform, harness plugin, `jarvis` preset | `ccs.doctor` runs and reports |
| **5** | CCS perception (§9) | screenshot, OCR, a11y tree, grounding ladder, post-action verification, frame store, threading model | `test_ccs_perception`, `test_ccs_grounding` green; real screenshot + a11y dump verified by hand |
| **6** | CCS input (§10) | SendInput/CGEvent/xdotool, key map, humanization, interlock integration | Real click and real keystroke land in a real app; `test_ccs_wave_groups` green |
| **7** | CCS windows/apps/system (§11) | window mgmt, launcher, processes, installer, terminal, power, services, registry, env, scheduler, network, clipboard, notifications | Each verified live via `ccs.doctor` |
| **8** | CCS browser (§12) | CDP driver, UIA fallback, profile copy, markdown reader, dialog handling | Drives a real logged-in Chrome session |
| **9** | Elevation (§13.4) | Elevated helper, named pipe, token, watchdog, secure-desktop detection, macOS/Linux paths | An elevated-window click succeeds; the UAC prompt appears at most once per session |
| **10** | CCS tool registration (§8) | ~90 schemas in `tools_list.json`, dispatch, wave-group classification, Headroom image guard | `test_ccs_tools_registry`, `test_headroom_image_guard` green |
| **11** | Delegated GUI autonomy (§8.8) | `computer_task`, `app_task`, `gui_explore`, `verify_gui_state`, `self_install_capability` | Completes a real multi-step GUI task end to end |
| **12** | Voice API (§15) | `/api/voice/*` routes, SSE with resume, subscriber management, error envelopes, loopback bind | `test_voice_api.py` green; `curl` samples in `DISCOVERY.md` |
| **13** | Event contract (§16) | `RuntimeEvent` extension, `narratable` selection, `AgentEvent` shape | `test_event_adapter` green against real captured SSE |
| **14** | Omni refactor (§30.1) | Split `live.py` into modules; `config.py`; `Supervisor` | Existing console behaviour byte-identical; `test_supervisor` green |
| **15** | Omni audio (§24) | Backend ABC, discovery, rate validation, native capture + resample, playback, barge-in, mute | `test_audio_*` green; `-9999` diagnostic reproduced and correctly reported |
| **16** | Omni vision (§25) | DPI-aware mss, monitor/window selection, camera probing, redaction, all five modes | `test_vision_*` green |
| **17** | Gemini client (§17) | Model discovery, full session config, receive loop, fn-call dispatch, watchdog, injection | Live session connects; a function call round-trips |
| **18** | Intent router (§18) | Declarations, validation, dispatch, concurrency, fallback classifier | `test_intent_routing_*` green at ≥ 90 % on the calibration sets |
| **19** | Bridge (§19) | `KratosBridge`, SSE parser, reconnect, health watcher | `test_bridge_*` green against the mock and against real Kratos |
| **20** | Narrator (§20) | Dictionary, throttle, coalesce, sanitize, LLM final summary | `test_narrator_*` green; sanitize is a hard gate |
| **21** | State machine + sessions (§21, §23) | `task_state.py`, `SessionRegistry`, queueing | `test_state_machine`, `test_session_continuity`, `test_concurrency` green |
| **22** | Steering, undo, cancel (§22) | End-to-end voice paths | `test_steering` green; manual §33.5 passes |
| **23** | Overlay (§26) | Assets pipeline, Qt thread, widget, ring, 3 buttons, tray, hotkeys, fallbacks | `test_overlay` green headless; looks right on a real display |
| **24** | Isolation & resilience (§27) | Full matrix, degradation paths, graceful shutdown | `test_isolation_matrix` green, cell by cell |
| **25** | Security pass (§28) | Redaction at all four boundaries, loopback verification, `.gitignore`, `.env.example` | `grep` sweep finds no secret in any artifact |
| **26** | Full test run (§32) | Omni + Kratos suites, regression comparison | Zero regressions; every new module green |
| **27** | Manual E2E (§33) | Every line executed and recorded | All boxes ticked |
| **28** | Acceptance (§34) + docs (§37) + Final Report (§38) | Everything | Complete |

**If a phase is blocked**, record the blocker, implement everything downstream that isn't blocked, and continue. Do not stall. Do not silently substitute a different design.

---

## 37. DOCUMENTATION TO UPDATE

1. **`README.md`** (Kratos) — add:
   - a **JARVIS** section at the top with the §14.2 topology diagram,
   - `sovereign` in the approval-modes table and the feature matrix,
   - a **Computer Control Subsystem** section: capability table, the grounding ladder, the interlock, elevation, panic, undo, audit,
   - the full new tool registry (~115 tools) grouped as in §8,
   - the Voice API reference (every `/api/voice/*` route),
   - the overlay section with a screenshot and the button/hotkey table,
   - new env vars, new extras (`[computer]`, `[overlay]`, `[voice]`, `[all]`),
   - updated directory tree,
   - updated test counts and module list,
   - updated badges (tool count, test count, Python versions),
   - troubleshooting: microphone, elevation, Wayland, macOS permissions, CDP, Kratos connectivity.
2. **`docs/jarvis.md`** — the whole integrated system: setup for both Python environments, the actual Kratos start command, the actual Omni start command, all five run modes, the overlay, cancellation, steering, undo, panic, the audit log, troubleshooting.
3. **`docs/computer-control.md`** — CCS reference: backends, capabilities per platform, the grounding ladder, the interlock, elevation internals, the wave groups, adding a new adapter, the self-install loop.
4. **`docs/sovereign-mode.md`** — the authority model, what it grants, the three control features, the eight invariants, how to step down to a lower mode.
5. **`docs/voice-api.md`** — every route with request/response examples and a captured SSE transcript.
6. **`documentation/web-api.md`** — add the `/api/voice/*` surface in the existing format.
7. **Omni README** (create `README-OMNI.md` if none exists) — the §4.2 flow diagram, both environments, both start commands, env vars, all run modes, overlay controls and hotkeys, cancellation, steering, undo, microphone troubleshooting, Kratos connectivity troubleshooting.
8. **`.env.example`** (both halves) — every var from §29, with a one-line comment each, placeholders only.
9. **`KRATOS.md`** — the project-memory file: record the CCS architecture decisions and the sovereign default so future runs inherit them.
10. **`DISCOVERY.md`** — committed, as the historical record of what was actually found.

---

## 38. FINAL REPORT TEMPLATE

Fill this in with **what was actually discovered and built**. Not a generic summary. Not aspirational language. Facts, file paths, line numbers, command output.

```markdown
# JARVIS Sovereign — Integration Report

## 1. Discovery
- Host platform / OS build:
- Omni interpreter + version:
- Kratos interpreter + version:
- Topology decision (two-process / in-process) and the proof:
- google-genai version:
- Live model id resolved to:                       (and how it was discovered)
- PyAudio status on this interpreter:              (stock / pyaudiowpatch / sounddevice — and why)
- `kratos-illu.png`: FOUND at … (WxH, alpha?) / NOT FOUND → placeholder generated at …
- Kratos test baseline BEFORE:  N modules / N tests — passed/skipped/failed
- Kratos test baseline AFTER:   N modules / N tests — passed/skipped/failed
- Regressions: none / list

## 2. Divergences (README vs code)
| # | README claim | Actual code (file:line) | Followed | Why |

## 3. Files
### Modified (path — one-line summary of the change)
### Created  (path — one-line summary)
### Deleted  (path — why)

## 4. Integration mechanism
- Selected (A–F from §6):
- Why:
- API endpoints used:
- SSE event format used (verbatim sample):
- In-process runtime class/functions used (if applicable):

## 5. Sovereign mode
- Enum member added at:
- Gate short-circuit at:
- New capability tags:
- Workspace-confinement change at:
- Default flipped in:
- Verified: no prompt fires for … (list what was tested)

## 6. Computer Control Subsystem
- Backend implemented for:                (platform)
- Capabilities online / total:
- Capabilities missing + the reason each:
- Input injection method:
- Perception channels working: screenshot / OCR / a11y / template / VLM grounding
- a11y technology:                        (UIA / AX / AT-SPI)
- Elevation method + UAC prompt count per session:
- Elevated-window injection working: yes/no — why
- Interlock measured yield latency:       ms
- Panic measured halt latency:            ms
- Browser: CDP / UIA fallback — which path was exercised
- Tools registered: N (list any from §8 that were NOT implemented, with the reason)

## 7. Voice API
- Routes implemented (with real line refs in web/server.py):
- SSE resume via Last-Event-ID: working / not — detail
- Bind address verified:

## 8. Omni
- Modules created:
- Intent routing mechanism: native function calling / prompt-based fallback — why
- Calibration accuracy on the §18.3 sets: chat N/N, task N/N, vision N/N, stop N/N, steer N/N
- Narration: measured lines spoken per 100 events; throttle interval enforced at
- Bridge reconnect: backoff sequence observed; Last-Event-ID sent: yes/no
- Audio: capture rate → send rate; resampler used; measured latency
- Barge-in flush latency:                 ms
- Vision: monitors detected; camera indices detected; redaction verified

## 9. Overlay
- Backend used:                           (PySide6 x.y / pywebview / tkinter)
- Asset pipeline: kratos-illu.png → derived files
- Ring states implemented: N/12
- Buttons verified truthful under: mic failure / screen failure / camera failure / Kratos down
- Hotkeys registered:
- Click-through verified:
- Position persistence verified:

## 10. Session ↔ Kratos session mapping — how it actually works:

## 11. Cancellation — what was found / what was built:

## 12. Steering — injection point in agent_loop.py:LINE — how it works:

## 13. Undo / snapshots — what is snapshotted, retention, verified restore:

## 14. Audit trail — path, record shape, redaction verified by:

## 15. Security
- Secrets grep-swept across: logs / SSE / audit / snapshots / transcripts — result:
- Web server bind:
- CDP bind:
- .gitignore additions:
- .env.example updated: yes/no

## 16. Python environment arrangement (final):

## 17. Tests
| Module | Tests | Result |
- Manual E2E (§33): N/M lines passed — list every failure with the cause
- Acceptance checklist (§34): N/M boxes — list every unchecked box with the reason

## 18. Known limitations
(be honest and specific — platform gaps, untested adapters, capabilities that need an
 install, OS trust boundaries, anything deferred)

## 19. Deferred / blocked work
| Item | Blocker | What unblocks it |

## 20. Exact commands to start the system
```bash
# 1. brain
# 2. senses + face
# 3. verification
```

## 21. Deviations from SHOULD requirements (each with a documented reason)
```

---

## 39. CLOSING DIRECTIVE

You are building the thing the user actually asked for: **a full-authority Jarvis.** Not a demo, not a chatbot with a microphone, not a coding assistant that happens to listen.

- Omni is the **face, the ears, the eyes, and the voice**. It must feel alive — the orb glowing, the ring breathing, the buttons telling the truth, the voice interruptible and natural.
- Kratos is the **brain and the hands**. It must actually *do things* — real windows, real keystrokes, real installs, real elevated commands, real browsers with real logins, real files anywhere on disk.
- The bridge is the **nervous system**. One runtime, one session, one event contract, no duplication.
- Sovereign means **sovereign**. No prompts. No hedging. No "I can't do that" unless the machine genuinely said so — and then a precise explanation of what's missing and how to fix it, spoken aloud.
- The only things that stop it are: the user's voice, the user's hotkey, the user's keystrokes on the physical keyboard, the laws of physics, the OS's own trust boundaries, and the eight self-preservation invariants that keep the system recoverable.

**Start with Phase 0. Write `DISCOVERY.md`. Verify everything. Then build all of it.**

Length of implementation is not a concern. Completeness and correctness are.

*Do not be sorry. Be better.*