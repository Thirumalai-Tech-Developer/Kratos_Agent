# Subsystem: Utilities & Tool Forging Pipeline
## Package: `kratos_agent.utils`

Source Directory: [`src/kratos_agent/utils/`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/)

---

### 1. Architectural Purpose & Overview

The `utils` package contains Kratos' built-in standard tool catalog, tool forging meta-programming pipelines, desktop helper utilities, shell escaping mechanisms, and execution telemetry.

```
src/kratos_agent/utils/
├── __init__.py          # Subsystem exports
├── async_runner.py      # Asyncio event loop bridges for synchronous callers
├── computer_tools.py    # Native window & desktop observation tools
├── shell_quote.py       # Cross-platform command argument escaping
├── step_tracker.py      # Execution step tracking & progress reporting
├── sync_tools.py        # Tool catalog synchronizer with tools_list.json
├── tool_creator.py      # Dynamic tool authoring & LLM tool synthesis
├── tool_sandbox.py      # Phase B AST validation & subprocess isolation
├── tools.py             # Curated foundational tools (filesystem, git, shell)
└── tools_list.json      # 180+ tool catalog metadata & schema declarations
```

---

### 2. Core Modules & Key Documentation

1. [`tool_sandbox.py.md`](file:///c:/Users/thiru/Documents/Kratos_Agent/documentation/utils/tool_sandbox.py.md):
   - `validate_tool_ast()`: Static AST security analysis rejecting dangerous modules and operations.
   - `execute_sandboxed_tool()`: Subprocess runner with stripped environment, tempdir isolation, and 10s timeout.
   - `verify_tool_in_sandbox()`: Automated companion smoke tests.
   - `log_forged_tool_audit()`: Audit logging in `.kratos/forged_tools/`.

2. [`tool_creator.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tool_creator.py):
   - `create_or_update_tool()`: Validates tool code, verifies in sandbox, logs audit trail, writes sandboxed wrapper into `tools.py`, updates `tools_list.json`, and triggers hot-reload.
   - `synthesize_and_register_tool()`: Prompts LLM to author missing tools autonomously.

3. [`tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/tools.py):
   - `read_file(path, offset, limit)`: Bounded file reader with line offsets.
   - `write_file(path, content)`: Atomic file writer.
   - `edit_file(path, target_text, replacement_text)`: Precise targeted text replacer with diff generation.
   - `run_terminal_command(command, timeout)`: Process executor capturing exit code, stdout, and stderr.
   - `grep_search(query, path)`: Ripgrep-style fast pattern matcher across the workspace.
   - `git_status()`, `git_diff()`: Native Git version control helpers.

4. [`computer_tools.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/utils/computer_tools.py):
   - `ui_tree_dump()`: Dumps focused desktop UI tree.
   - `active_window_info()`: Obtains focused process name and window bounds.
   - `screenshot_capture()`: Captures desktop or window screenshots for vision grounding.
