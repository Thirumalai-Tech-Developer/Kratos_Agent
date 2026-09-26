# Subsystem: System, Diagnostics, Event Bus & Specialized Executors
## Packages: `capabilities`, `diagnostics`, `events`, `executors`, `input`, `output`, `performance`, `interfaces`, `tui`, `web`

Source Directories:
- [`src/kratos_agent/capabilities/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/capabilities/)
- [`src/kratos_agent/diagnostics/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/diagnostics/)
- [`src/kratos_agent/events/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/)
- [`src/kratos_agent/executors/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/executors/)
- [`src/kratos_agent/output/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/output/)
- [`src/kratos_agent/tui/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/)
- [`src/kratos_agent/web/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/web/)

---

### 1. Architectural Purpose & Overview

This layer manages event distribution, diagnostic tracing, specialized tool executors, and presentation interfaces:
1. **Event Bus (`events.bus`)**: Publish-subscribe message bus distributing lifecycle events across the agent loop, telemetry loggers, and user interfaces.
2. **Specialized Executors (`executors`)**: Dedicated domain executors for terminal shells, code compilation, filesystem manipulation, and window management.
3. **Diagnostics & Tracing (`diagnostics`)**: Captures stack traces, operation latencies, and system health status.
4. **Terminal User Interface (`tui`)**: Rich-powered console renderer featuring live progress spinners, syntax-highlighted diffs, tool execution panels, and status bars.
5. **Web Gateway & API Server (`web.server`)**: FastAPI application exposing REST endpoints (`/api/chat`, `/api/health`, `/api/tools`) and SSE streams for web frontend integration.

---

### 2. Core Modules & Key Classes

#### Event Bus (`kratos_agent.events`)
- **[`bus.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/events/bus.py): `EventBus`**:
  - `subscribe(event_type: str, callback: Callable[[Event], None])`
  - `publish(event: Event) -> None`
  - Asynchronously dispatches events without blocking the main agent execution thread.

#### Terminal UI (`kratos_agent.tui`)
- **[`live_renderer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/live_renderer.py): `LiveRenderer`**:
  - Full-screen dynamic terminal output using `rich.live.Live`.
  - Renders streaming tokens, active tool calls, elapsed time, and diff previews.
- **[`status_bar.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/tui/status_bar.py)**:
  - Persistent terminal footer showing current mode (`Sovereign` / `Supervised`), active model, token count, and step index.

#### Web Server (`kratos_agent.web.server`)
- FastAPI ASGI application.
- Supports:
  - CORS with configurable origins.
  - Rate limiting via sliding window.
  - Streaming completions over SSE.
  - Live session WebSocket for avatar and audio streaming.
