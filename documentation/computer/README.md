# Subsystem: Computer-Use Runtime & Orchestration
## Package: `kratos_agent.computer`

Source Directory: [`src/kratos_agent/computer/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/)

---

### 1. Architectural Purpose & Overview

The `computer` package provides the high-level orchestration runtime for computer use. While `ccs` provides the low-level OS drivers (UIA / AT-SPI), `computer` implements the cognitive agent loop specifically for desktop and application control:
- **Observation**: Captures structured snapshots of the desktop, open applications, and browser state (`observer.py`).
- **Execution**: Safely executes multi-step desktop tasks via discrete actions (`executor.py`).
- **State Management & Caching**: Maintains an active model of open windows, focused controls, and clipboard contents (`state.py`, `state_cache.py`).
- **Verification**: Evaluates post-conditions to verify desktop actions succeeded (`verifier.py`).
- **Recovery**: Recovers from unexpected dialogs, modal popups, and application freezes (`recovery.py`).

```
src/kratos_agent/computer/
├── __init__.py          # Subsystem exports
├── capabilities.py      # Desktop capability probing (OS version, display count)
├── executor.py          # Action dispatcher for desktop interactions
├── manager.py           # ComputerManager lifecycle coordinator
├── observer.py          # Structured desktop and window observer
├── permissions.py       # Fine-grained computer permission policies
├── planner.py           # Computer action planning & task breakdown
├── recovery.py          # Modal dialog dismissal & error recovery
├── state.py             # Desktop state representation
├── state_cache.py       # State caching with TTL to avoid redundant UI queries
├── verifier.py          # Desktop assertion & goal verification
├── apps/                # Application-specific adapters (VSCode, Notepad, etc.)
├── browser/             # Low-level browser driver & manager
├── filesystem/          # Desktop filesystem utilities
├── gui/                 # GUI element finders & tree traversal
├── tools/               # Computer tools registered with ToolRegistry
└── vision/              # Optional visual fallback verification
```

---

### 2. Core Modules & Key Methods

#### [`manager.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/manager.py): `ComputerManager`
- Central controller coordinating desktop observation, planning, execution, and verification.
- **Methods**:
  - `observe() -> DesktopState`: Captures active window, running apps, and accessibility tree.
  - `execute_action(action: ComputerAction) -> ActionResult`: Dispatches desktop action through security and recovery filters.

#### [`observer.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/observer.py): `ComputerObserver`
- Produces clean, token-efficient representations of the desktop for the LLM.
- Converts raw accessibility trees into high-level summaries (focused window, interactive buttons, text inputs, status bars).

#### [`recovery.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/recovery.py): `ComputerRecovery`
- Automatically handles disruptions:
  - Detects blocking modal dialogs ("Save Changes?", "Update Available?") and dismisses or confirms them intelligently.
  - Recovers keyboard focus if an application loses focus unexpectedly.

#### [`verifier.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/computer/verifier.py): `ComputerVerifier`
- Authoritatively checks that a requested desktop interaction actually took effect before moving to the next step.
