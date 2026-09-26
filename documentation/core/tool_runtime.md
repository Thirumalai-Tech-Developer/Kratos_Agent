# Subsystem: Tool Runtime & Permission Enforcement
## Module: `kratos_agent.core.tool_runtime`

Source File: [`src/kratos_agent/core/tool_runtime.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/core/tool_runtime.py)

---

### 1. Architectural Purpose & Overview

The `tool_runtime.py` module defines the authoritative contract for tool discovery, registration, schema validation, and permission control. In Kratos, models are never given direct or untracked access to host functions. Every tool is wrapped in a `ToolSpec` and registered with a `ToolPermission` tier.

---

### 2. Permission Levels (`ToolPermission`)

Kratos enforces a 4-tier security model:

```python
class ToolPermission(str, Enum):
    READ = "read"          # Inspect files, list directories, read memory, status
    WRITE = "write"        # Create/modify files, update memory, write clipboard
    EXECUTE = "execute"    # Run shell commands, launch processes, execute python
    ADMIN = "admin"        # Modify system settings, format tools, elevate privileges
```

#### Permission Mapping Table

| Category | Tools | Permission Tier | Gating in Supervised Mode |
|---|---|---|---|
| **Filesystem Read** | `read_file`, `list_directory`, `grep_search` | `READ` | Auto-allowed |
| **Git Read** | `git_status`, `git_diff` | `READ` | Auto-allowed |
| **Memory Read** | `read_memory`, `list_skills` | `READ` | Auto-allowed |
| **Inspection** | `computer_observe`, `computer_inspect`, `ui_tree_dump` | `READ` | Auto-allowed |
| **Filesystem Write**| `write_file`, `edit_file` | `WRITE` | User Confirmation |
| **Memory Write** | `save_memory`, `clear_memory` | `WRITE` | User Confirmation |
| **Process Execution**| `run_terminal_command`, `execute_script` | `EXECUTE` | Explicit Approval Prompt |
| **Tool Forging** | `self_tool_creator`, `/create-tool` | `ADMIN` | Sandbox Verification & Log |

---

### 3. Key Classes & Methods

#### `ToolSpec`
Dataclass declaring a tool's model-visible interface:
- `name` (`str`): Unique identifier (e.g., `read_file`, `edit_file`).
- `description` (`str`): Detailed description explaining when and how to call the tool.
- `parameters` (`dict[str, Any]`): JSON Schema describing input arguments.
- `permission` (`ToolPermission`): Required security clearance.

#### `ToolRegistry`
Central thread-safe registry holding all active tools:
- `register(spec: ToolSpec, handler: Callable) -> None`: Registers a handler function under the given specification.
- `get(name: str) -> tuple[ToolSpec, Callable] | None`: Retrieves the specification and handler.
- `list_specs() -> list[ToolSpec]`: Returns all registered tool specifications formatted for LLM function calling schemas.
- `execute(name: str, args: dict[str, Any]) -> Any`: Dispatches execution with argument validation.

#### `legacy_tool_registry(workspace: Path) -> ToolRegistry`
Adapts curated Kratos tools (`utils/tools.py`, `utils/computer_tools.py`, `computer/tools/`) into a unified `ToolRegistry` instance, filtering out deprecated coordinate-based mouse helpers to enforce accessibility-tree based computer use.
