# Tools, Memory, Persistence, and Data Contracts

## Built-in tools

The curated handlers live in `src/kratos_agent/utils/tools.py` and are described in `utils/tools_list.json`. The registry derives each JSON schema from the Python signature.

| Function | Arguments | Behavior |
| --- | --- | --- |
| `format_diff_stat` | `added`, `removed`, `max_width=8` | Builds a Rich git-style diff bar. |
| `clean_command` | `cmd_str` | Removes markdown/JSON wrapper artifacts from shell input. |
| `is_persistent_server_command` | `command` | Detects dev/start/serve processes that should remain in the background. |
| `run_terminal_command` | `command` | Applies approval and hooks, executes via `subprocess`, streams status, truncates output, records command history, and returns output plus exit code. |
| `clean_file_path` | `fp_str` | Normalizes quote/prefix/URL artifacts and redirects scratch paths into the workspace. |
| `write_file` | `file_path`, `content` | Creates parent directories, writes UTF-8 content, records changes, and returns a result. |
| `read_file` | `file_path` | Reads text with workspace/path normalization and bounded output. |
| `edit_file` | `file_path`, `target_text`, `replacement_text` | Replaces an exact target once; reports missing or ambiguous targets instead of silently changing the wrong text. |
| `list_directory` | `directory_path="."`, `max_depth=2` | Returns a bounded tree/listing. |
| `grep_search` | `query`, `directory_path="."`, `is_regex=False` | Searches text recursively with literal or regex matching. |
| `fetch_url` | `url` | Fetches an HTTP page for research. |
| `google_search` | `query` | Searches the configured search provider. |
| `calculate_expression` | `expression` | Evaluates the supported arithmetic expression path and returns a string result. |
| `git_status` | none | Returns repository status. |
| `git_diff` | `staged=False` | Returns staged or unstaged diff. |
| `git_commit` | `message=""` | Creates a commit through the git helper. |
| `git_push` | `branch=""` | Pushes the selected branch. |
| `git_create_pr` | `title=""`, `body=""`, `base="main"` | Creates a pull request through the configured git integration. |

`tools.py` also uses `step_tracker`, `memory`, `approval_gate`, `hook_registry`, and `git_tools`; tool failures are returned as strings so the agent loop can observe and repair them.

## Tool forging

`utils/tool_creator.py` exposes:

- `register_tools_updated_callback(callback)` and `notify_tools_updated()`: notify reload listeners.
- `create_or_update_tool(tool_name, description, python_code, parameters_schema=None)`: validates a generated function/schema, writes the Python handler and manifest entry, and reports the result.
- `self_tool_creator(tool_spec)`: parses a tool specification and delegates to `create_or_update_tool`.
- `synthesize_and_register_tool(tool_name, requirement, brain)`: asks the model for JSON containing a function and schema, extracts it, persists it, and returns an error string on failure.

Generated code is an execution boundary. Review generated tools before enabling them in a production workspace.

## Local session model

`AgenticSession` stores:

- identity: `session_id`, title, model, created/updated timestamps;
- conversation: turns with user query, assistant reply, tool records, and turn index;
- execution state: plan JSON, changed files, verification JSON, notes, and command records.

The memory manager serializes session state under `.kratos/sessions`, while `D1Client` can persist the same concepts to SQLite/D1.

## D1 tables

| Table | Important columns | Use |
| --- | --- | --- |
| `sessions` | `id`, `title`, `model`, timestamps, status, plan/files/verification/notes JSON | Session index and current state. |
| `turns` | `id`, `session_id`, `turn_index`, timestamp, user query, reply, tools JSON | Conversation history. |
| `agentic_events` | `id`, `session_id`, `turn_id`, `kind`, timestamp, payload JSON | Replayable execution trace. |
| `commands` | `id`, `session_id`, timestamp, command, return code, output preview | Terminal audit trail. |
| `workspace_files` | `path`, `content`, `updated_at` | Edge virtual workspace file contents. |

Foreign keys cascade session deletion into turns, events, and commands. The Worker and Pages adapter initialize the schema defensively on first request.

## Runtime contracts

Tool calls use `ToolCall(call_id, name, arguments)`. Tool results use `ToolResult(call_id, name, content, is_error=False, duration_ms=0)`. `ToolSpec` carries `name`, description, parameter schema, permission, and source. `RuntimeEvent` carries an `EventKind`, payload, optional turn ID, and timestamp. These contracts are the stable boundary between model adapters, tools, persistence, TUI, and web streaming.
