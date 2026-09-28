# Tools, memory, and data boundaries

## Tool execution

Built-in tools are registered from `src/kratos_agent/utils/tools.py` and `src/kratos_agent/core/tool_runtime.py`. MCP tools are namespaced as `mcp__<server>__<tool>`. Both pass through the same JSON-schema validation, permission boundary, risk policy, event logging, and result handling.

The built-in MCP servers are:

| Server | Purpose | Default |
| --- | --- | --- |
| `computer-use` | Browser and desktop interaction via `@zavora-ai/computer-use-mcp@7.4.0` using the `core` profile. | Enabled; set `KRATOS_COMPUTER_USE_MCP=false` to disable. |
| `openpets` | Companion controls and speech bubble via `@open-pets/mcp@4.0.0`. | Enabled; set `KRATOS_OPENPETS_MCP=false` to disable. |
| `context7` | Current library documentation through the hosted Context7 MCP. | Enabled; set `KRATOS_CONTEXT7_MCP=false` to disable. `CONTEXT7_API_KEY` is optional. |
| `composio` | Composio Connect meta-tools for discovering and using connected apps. | Disabled without `COMPOSIO_CONSUMER_API_KEY`; set the key and `KRATOS_COMPOSIO_MCP=true`, then authorize individual apps through OAuth. |
| `gitnexus` | Local repository graph and symbol relationship tools using GitNexus `1.6.12`. | Enabled when the MCP package can start. Run the one-time index command below; set `KRATOS_GITNEXUS_MCP=false` to disable. |

User MCP servers are configured in `.kratos/mcp.json`. Kratos does not import another agent runtime or read its private tool configuration. MCP connection failures are reported per server and do not switch the reasoning model.

### Set up the integrations

Context7 uses `https://mcp.context7.com/mcp`. An API key is optional; set `CONTEXT7_API_KEY` in `.env` if you have one. Use `/mcp reload` after changing the environment.

Composio Connect uses `https://connect.composio.dev/mcp` and the `x-consumer-api-key` header. Put your Composio consumer key in `.env` as `COMPOSIO_CONSUMER_API_KEY`, set `KRATOS_COMPOSIO_MCP=true`, and run `/mcp reload`. The agent can discover app tools and present their OAuth connection flow; users still approve each account connection. Keep this server disabled until you are ready to connect real accounts.

GitNexus needs Node.js 22.18+ or 24.11+ and pnpm when available. From the repository root, build its local graph without generating or changing agent instruction files:

```powershell
pnpm --allow-build=@ladybugdb/core --allow-build=gitnexus --allow-build=tree-sitter dlx gitnexus@1.6.12 analyze --index-only .
```

Kratos stores that local index under `.gitnexus/` (ignored by Git). Re-run the command when the graph is stale. GitNexus is distributed under PolyForm Noncommercial 1.0.0; review that license before using it for commercial work.

## Consequence policy

Read operations are available under the read permission. Workspace writes must remain within the workspace and must satisfy the active approval mode. The risk policy treats the following as significant consequence: external communication or publication, destructive data changes, financial transactions or bookings, account/security changes, and system installation/configuration. Such an action must match a direct user request and the tool call must supply the concrete target.

For observable work, completion also requires evidence. A tool response saying “success” or a command starting does not prove the intended outcome. Browser assertions run against live browser state before passing evidence to the completion gate.

## Skills and instructions

Skills are loaded from Kratos's supported `SKILL.md` roots and are included as context instructions. They do not install another model, agent, or runtime. The active workspace's `AGENTS.md` and Kratos instruction modules are included through the instruction/context pipeline.

The bundled Kratos workflow pack includes task planning/execution/review/verification (`superpowers`), decision interviews (`grill-me`), PRD drafting (`to-prd`), test-first implementation (`tdd`), bug diagnosis (`diagnose`), architecture review (`zoom-out`), concise response mode (`caveman`), security audits (`security-audit`), Context7 usage, GitNexus graph usage, Composio app actions, and web-app design/testing/deployment/database guidance. Run `/skill list` to see the catalog and `/skill show <name>` to inspect a workflow. Kratos selects relevant skill summaries from the active request and loads full instructions with `read_skill`.

The Matt Pocock aliases preserve the names you asked for: current upstream renamed `to-prd` to `to-spec` and `diagnose` to `diagnosing-bugs`; `zoom-out` and `caveman` are not present in the current upstream catalog. Kratos provides native equivalents under those requested names.

## Persisted data

Session history is stored by the memory subsystem. Detailed runtime events are written as JSONL under `.kratos/sessions/<session-id>/events.jsonl`. Request snapshots redact common secret fields before writing trace records. API credentials are read from environment variables and are not copied into MCP configuration files.

## Reasoning and speech

The first-party `KratosClient` sends reasoning and tool schemas to the configured local Kratos gateway using `/v1/chat/completions`. `KRATOS_MODEL` is the only reasoning model. Gemini receives only marked speech text for audio rendering. Windows System.Speech recognizes user speech locally and forwards its text to Kratos.
