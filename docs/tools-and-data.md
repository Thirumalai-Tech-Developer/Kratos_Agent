# Tools, memory, and data boundaries

## Tool execution

Built-in tools are registered from `src/kratos_agent/utils/tools.py` and `src/kratos_agent/core/tool_runtime.py`. MCP tools are namespaced as `mcp__<server>__<tool>`. Both pass through the same JSON-schema validation, permission boundary, risk policy, event logging, and result handling.

The built-in MCP servers are:

| Server | Purpose | Default |
| --- | --- | --- |
| `computer-use` | Browser and desktop interaction via `@zavora-ai/computer-use-mcp@7.4.0` using the `core` profile. | Enabled; set `KRATOS_COMPUTER_USE_MCP=false` to disable. |
| `openpets` | Companion controls and speech bubble via `@open-pets/mcp@4.0.0`. | Enabled; set `KRATOS_OPENPETS_MCP=false` to disable. |

User MCP servers are configured in `.kratos/mcp.json`. Kratos does not import another agent runtime or read its private tool configuration. MCP connection failures are reported per server and do not switch the reasoning model.

## Consequence policy

Read operations are available under the read permission. Workspace writes must remain within the workspace and must satisfy the active approval mode. The risk policy treats the following as significant consequence: external communication or publication, destructive data changes, financial transactions or bookings, account/security changes, and system installation/configuration. Such an action must match a direct user request and the tool call must supply the concrete target.

For observable work, completion also requires evidence. A tool response saying “success” or a command starting does not prove the intended outcome. Browser assertions run against live browser state before passing evidence to the completion gate.

## Skills and instructions

Skills are loaded from Kratos's supported `SKILL.md` roots and are included as context instructions. They do not install another model, agent, or runtime. The active workspace's `AGENTS.md` and Kratos instruction modules are included through the instruction/context pipeline.

## Persisted data

Session history is stored by the memory subsystem. Detailed runtime events are written as JSONL under `.kratos/sessions/<session-id>/events.jsonl`. Request snapshots redact common secret fields before writing trace records. API credentials are read from environment variables and are not copied into MCP configuration files.

## Reasoning and speech

The first-party `KratosClient` sends reasoning and tool schemas to the configured local Kratos gateway using `/v1/chat/completions`. `KRATOS_MODEL` is the only reasoning model. Gemini receives only marked speech text for audio rendering. Windows System.Speech recognizes user speech locally and forwards its text to Kratos.
