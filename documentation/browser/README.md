# Subsystem: Browser Automation & Integration
## Directory: `kratos_agent.browser`

Source Directory: [`src/kratos_agent/browser/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/browser/)

---

### 1. Architectural Purpose & Overview

The `browser` package acts as the unified high-level facade for browser lifecycle management, CDP (Chrome DevTools Protocol) diagnostics, and Playwright automation. It abstracts multi-target browser tabs and pages, exposing clean readiness probes and session managers for the autonomous agent.

```
src/kratos_agent/browser/
├── __init__.py      # Package barrel export
├── cdp.py           # Chrome DevTools Protocol diagnostics & health checks
├── playwright.py    # PlaywrightDriver delegation & capability verification
├── readiness.py     # Resilient readiness polling & timeout probe
├── session.py       # BrowserSessionManager context facade
└── tabs.py          # Tab enumeration & active target inspection
```

---

### 2. Module Specifications

#### [`session.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/browser/session.py): `BrowserSessionManager`
- **Class Purpose**: Single authoritative browser context facade.
- **Methods**:
  - `discover() -> dict[str, Any]`: Discovers active browser manager, current active target page ID, and lock status.
  - `open(url: str) -> Any`: Navigates the active browser target to a URL.
  - `reuse_or_open(url: str) -> Any`: Idempotently navigates existing tab or spawns a new one.

#### [`readiness.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/browser/readiness.py): `wait_until_ready`
- **Purpose**: Eliminates race conditions during web page loads, DOM readiness, or browser daemon spin-up.
- **Signature**:
  ```python
  wait_until_ready(
      probe: Callable[[], bool],
      timeout: float = 15.0,
      interval: float = 0.25,
  ) -> BrowserReadiness
  ```
- **Returns**: `BrowserReadiness(ready: bool, reason: str)`

#### [`cdp.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/browser/cdp.py): `cdp_health`
- **Signature**: `cdp_health() -> dict[str, Any]`
- **Returns**: `{"available": bool, "manager": str}` or error details.

#### [`tabs.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/browser/tabs.py): `list_tabs`
- **Signature**: `list_tabs() -> list[Any]`
- **Returns**: List of active browser tab references currently open under the manager.

#### [`playwright.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/browser/playwright.py)
- Re-exports `PlaywrightDriver` and `can_report_success` from the lower-level driver subsystem in `kratos_agent.computer.browser.playwright`.
