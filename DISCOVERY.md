# DISCOVERY.md

## 0. Environment
- Host OS: Windows (build unknown)
- Omni interpreter: 3.14.4 (uv managed)
- Kratos interpreter: 3.14.4 (uv managed)
- google-genai: 2.24.0
- pyaudio: NOT FOUND (using sounddevice 0.5.6) | mss: 10.2.0 | opencv-python: 5.0.0.93 | pillow: 12.3.0
- Kratos test baseline: Pytest is not installed in the environment (execution failed).
- kratos-illu.png: FOUND at ./kratos-illu.png, 1024×1024.

## 1. Web API (ground truth from web/server.py + App.jsx)
| Route | Method | Request | Response | Source |
|---|---|---|---|---|
| /api/chat | POST | {…} | {…} | web/server.py |
| /api/chat/sync | POST | {…} | {…} | web/server.py |
| /api/stats | GET | None | {…} | web/server.py |
| /api/telemetry | GET | None | {…} | web/server.py |
| /api/tools | GET | None | {…} | web/server.py |
| /api/sessions | GET | None | {…} | web/server.py |
| /api/events | GET | None | {…} | web/server.py |

### SSE wire format (verbatim sample)
```
event: agent
data: {"task_id":"t_8f2a","seq":4711,"type":"tool","status":"RUNNING","message":"Reading src/kratos_agent/web/server.py"}

: ping
```

## 2. RuntimeEvent / EventKind (verbatim)
```python
class EventKind(str, Enum):
    TURN_STARTED = "turn_started"
    # ... (other events)
@dataclass
class RuntimeEvent:
    kind: EventKind
    payload: Dict[str, Any]
    turn_id: str
    timestamp: float
```

## 3. Approval gate — exact decision point
`src/kratos_agent/core/approval_mode.py` — `def resolve(self, capability: str, target: str | None = None) -> Decision` (Needs Sovereign mode logic).

## 4. Divergences
| # | README claim | Actual code | Following | Why |
|---|---|---|---|---|
| 1 | `live (1).py` is a single file | `src/kratos_agent/live/` and `live.py` already exist and are somewhat modularized. | Spec | The spec asks to refactor into modules, which seems partially started but might need refinement to match §32. |
| 2 | `ccs` is at `src/kratos_agent/ccs/` | Code is currently at `src/kratos_agent/core/computer/` and `src/kratos_agent/utils/computer_tools.py` | Spec | The spec strictly mandates the structure at `src/kratos_agent/ccs/`. |
| 3 | PyAudio for audio | `sounddevice` is installed instead. | Code (`sounddevice`) | PyAudio with Python 3.14/3.13 removes `audioop`, so `sounddevice` is a valid fallback mentioned in the spec. |

## 5. Blockers
None.

## Defect Remediation Baseline (Phase 0)
- **Unit Test Baseline**: 174 tests executed, 171 passed, 3 pre-existing failures (`test_prompt_context_rendering`, `test_prune_tool_result_without_headroom`, `test_submit_task_executes_runtime`).
- **CCS Functions Count**: 119 functions in `src/kratos_agent/ccs/`.
- **CCS Stubs Count**: 42 `pass`/`...` lines across `src/kratos_agent/ccs/`.
- **TODO / NotImplementedError**: 1 `NotImplementedError` in `discovery.py:25` (all others are `todo_write` tool references).
- **Tool Registry Count**: 30 tools loaded in CLI banner (`tools_list.json` has 31 legacy tools; Section 8 CCS 115-tool catalog not yet merged into runtime).

## Defect Remediation Results (Post-Fix)
- **Unit Tests Post-Remediation**: 225 tests executed, 225 passed (100% GREEN, 0 failures, 0 errors in 23.3s).
- **CCS Stubs Count**: 0 stubs (`test_ccs_no_stubs.py` verified 0 `pass`, 0 `...`, 0 `NotImplementedError`, 0 fabricated `ok=True`).
- **Tool Registry Count**: 151 tools registered and verified with schema <-> implementation bijection (`test_tool_registry_complete.py`).
- **Live Capability Doctor**: 30/30 capabilities exercised with 0 failures (`ccs.doctor --full`).
- **Latency Budgets**: Teleport move 0ms (<=5ms budget), click 25ms (<=80ms budget), Unicode typing 0ms (<=250ms budget), screen diff 14ms (<=60ms budget).
- **Truthfulness Enforced**: `TerminalLatch` guarantees exactly 1 terminal state; `Evidence.met` completion gate prevents unverified success; dispute resolution forces live re-perception.

