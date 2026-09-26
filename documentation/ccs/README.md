# Subsystem: Computer Control Subsystem (CCS)
## Package: `kratos_agent.ccs`

Source Directory: [`src/kratos_agent/ccs/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/)

---

### 1. Architectural Purpose & Overview

The Computer Control Subsystem (CCS) provides accessibility-driven computer use. Rather than relying on unreliable pixel-coordinate mouse clicks and visual hallucinations, CCS interacts directly with the operating system's native **Accessibility Tree**:
- **Windows**: Microsoft UI Automation (UIA) via COM interfaces.
- **Linux**: AT-SPI (Assistive Technology Service Provider Interface) via D-Bus.

This architectural shift allows Kratos to inspect UI controls by name, role, automation ID, and value with 100% deterministic precision, even when windows are resized, shifted, or partially occluded.

```
src/kratos_agent/ccs/
├── __init__.py          # Package exports
├── assertions.py        # Authoritative UI assertions (check text, states, controls)
├── base.py              # Abstract OS driver and accessibility node interfaces
├── discovery.py         # Window, process, and application discovery
├── doctor.py            # Diagnostic health check & self-repair (UIA, COM, permissions)
├── elevated_helper.py   # Admin/root elevation detection & safe privilege delegation
├── linux.py             # Linux AT-SPI accessibility driver
├── safety_ops.py        # Out-of-bounds guards & runaway interaction blockers
├── tasks.py             # Reusable automation task routines
└── windows.py           # Windows UI Automation (UIA) COM driver
```

---

### 2. Core Modules & Key Functions

#### [`windows.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/windows.py): `WindowsDriver`
- Interfaces directly with `UIAutomationCore.dll` via `comtypes`.
- **Key Methods**:
  - `get_active_window() -> AccessibilityNode`: Inspects the currently focused desktop window.
  - `find_element(name: str, control_type: str | None = None) -> AccessibilityNode`: Queries the UIA tree for matching UI elements.
  - `dump_tree(max_depth: int = 4) -> dict[str, Any]`: Dumps hierarchical accessibility tree suitable for LLM comprehension.

#### [`assertions.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/assertions.py): `UIAssertionEngine`
- Verifies UI state authoritatively:
  - `assert_element_exists(name: str)`
  - `assert_element_text(name: str, expected_text: str)`
  - `assert_element_enabled(name: str)`
  - `assert_window_title_contains(substring: str)`

#### [`doctor.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/doctor.py): `ccs_doctor`
- Diagnostics engine that runs preflight checks on:
  1. COM threading initialization (STA/MTA).
  2. UI Automation availability.
  3. Display scaling and DPI awareness.
  4. Accessibility permissions.
- Returns actionable repair recommendations if any system probe fails.

#### [`safety_ops.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/ccs/safety_ops.py)
- Protects the host system against destructive or out-of-bounds interactions:
  - Validates bounding boxes before any focus or interaction.
  - Rate-limits keystrokes to prevent runaway input loops.
  - Enforces confirmation gates when interacting with sensitive system dialogues (e.g. UAC prompts, security warnings).
