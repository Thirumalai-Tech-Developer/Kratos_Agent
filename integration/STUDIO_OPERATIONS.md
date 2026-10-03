# Kratos Studio operations

The launcher runs the imported OmniRoute service and Kratos agent from this checkout. It does not need the original `veo_route` source directory. Use the project's supported Python version (`.python-version` is 3.12): run `uv sync`, then `uv run kratos-studio setup` once to install and build the bundled frontends. Start it with `uv run kratos-studio --workspace <your-workspace>`. The gateway UI is at `/dashboard/kratos` on port 20128 by default. `uv run kratos-studio doctor` reports build prerequisites and the private credentials file location.

The gateway uses `<workspace>/.kratos/studio/gateway` by default. The first launch generates `studio-secrets.json` there with an initial password, JWT secret, storage encryption key, and persistent `KRATOS_GATEWAY_API_KEY`. Keep that file private and backed up with the data directory. The managed inference key authenticates Kratos to gateways started by this launcher; explicit `OMNIROUTE_API_KEY`/`ROUTER_API_KEY` and `KRATOS_API_KEY` settings take precedence. An older or separately started gateway needs an accepted `KRATOS_API_KEY` in the workspace `.env`, or a restart through the updated launcher. Kratos runtime traffic uses a separate per-launch internal token and sends `x-omniroute-no-memory: true`; Kratos remains the memory owner for its tasks. OmniRoute's native clients retain their own memory settings.

The launcher loads the integration checkout's root `.env` for Kratos settings, then `services/omniroute/.env` for OmniRoute settings. Existing process environment variables and root settings take precedence. The private `studio-secrets.json` always supplies the active JWT and storage encryption keys so an imported database keeps its original encryption key. Both `.env` files are local, ignored by Git, and must be copied separately when moving the checkout.

## Import existing OmniRoute data

Stop Kratos Studio, then run:

```powershell
uv run kratos-studio import-data --workspace C:\path\to\workspace --source-data-dir C:\Users\thiru\.omniroute --source-env C:\Users\thiru\Documents\veo_route\.env
```

Set the source paths to the actual data directory and environment file used by the existing OmniRoute installation. The environment file must contain its `STORAGE_ENCRYPTION_KEY`, or encrypted provider credentials cannot be retained. The command copies the data tree, makes a consistent SQLite snapshot including committed WAL data, and stores the source encryption key in Studio's private secrets file. It never writes to the original data directory. If Studio already has data, its previous directory is renamed to a dated `gateway.rollback-*` sibling and the command prints that path. A failed final replacement restores the previous directory. To roll back later, stop Studio and move the current gateway directory aside before moving the printed rollback directory back into place.

An imported database retains its existing login password hash; use the password from the original OmniRoute installation. The generated `INITIAL_PASSWORD` applies only to a new database.

## Terminal CLI and MCP management

Run the integrated terminal agent:

```powershell
uv run --no-sync kratos-studio run --cli --workspace .
```

Equivalent commands are `kratos-studio cli --workspace .` and `kratos --cli --workspace .`. The launcher starts its own gateway if the selected port is free. If Studio already serves a ready gateway there, the CLI connects to it and leaves it running on exit. CLI mode uses the foreground terminal and does not start a duplicate agent web server or open a browser. A listener that fails the gateway health/model checks is reported as an error.

For a terminal-only installation, run `uv run kratos-studio setup --cli` once. This installs and builds the gateway without installing/building the agent web frontend; it does not open the terminal agent. `--dev` uses the gateway development server and skips its production build during setup. The existing full setup and web run commands remain available.

On a slow first launch, the CLI waits up to 10 minutes for the gateway health endpoint before reporting a startup error. Use `--startup-timeout <seconds>` to change that bound; the detailed gateway log is `.kratos/studio/logs/gateway.log`.

Use `--port 20228` to select another local gateway port. The launcher supplies matching chat and model endpoints before importing the agent runtime. It loads process settings first, then the selected workspace `.env`, the integration checkout `.env`, and the bundled gateway `.env`. Set `KRATOS_MODEL` to an exact ID served by that gateway; the launcher checks the model listing without issuing a chat request. Workspaces share their local `.kratos/mcp.json`, skills, and sessions between the web and terminal interfaces. Use `/help` for the interactive commands and `/doctor` to test model transport.

Manage connections inside the interactive CLI too:

```text
/mcp add https://example.com/mcp --name docs
/mcp check docs
/mcp disable docs
/mcp enable docs
/mcp remove docs
/mcp import C:\path\to\mcp.json
/mcp reload
```

Configuration changes made through these interactive commands apply immediately to the CLI session. A separate running Studio web process needs its own Reconnect or restart.

Manage MCP configuration without starting the agent or other configured MCP servers:

```powershell
uv run --no-sync kratos mcp add https://example.com/mcp --name docs --workspace .
uv run --no-sync kratos mcp list --workspace .
uv run --no-sync kratos mcp check docs --workspace .
uv run --no-sync kratos mcp disable docs --workspace .
uv run --no-sync kratos mcp enable docs --workspace .
uv run --no-sync kratos mcp remove docs --workspace .
```

`add` requires `--replace` to overwrite an existing name. Use `configure <name> <json-file>` for a command, arguments, or environment/header references, and `import <path>` for a local MCP configuration or plugin directory. `check` connects only the selected enabled server and lists its tools. Other commands only change configuration; apply changes with Reconnect in the MCP page or restart Kratos. The same commands are available under `kratos-studio mcp`.

Remote MCP connections currently support HTTP/SSE with optional header credentials. Interactive OAuth authorization and general remote plugin/skill installation remain unfinished.

## Verified recovery memory

Agent mode automatically remembers supported tool recoveries in the selected workspace. A failed call must be followed by a changed, successful call on the same task and tool; terminal recovery also requires an explicit exit code of zero. The task and plan must complete and pass the runtime's verification checks before a lesson is saved. A successful call issued together with a failing call cannot count as its correction. Failed or interrupted runs do not publish lessons.

The current categories are tool arguments, shell syntax, missing files, missing dependencies, and timeouts. The runtime saves fixed correction templates and scope metadata rather than commands, output, credentials, or private reasoning. This is a bounded implementation inspired by [Reflexion](https://arxiv.org/html/2303.11366v4); it does not train model weights or make additional model requests. A lesson describes an observed operational recovery and does not establish the accuracy of a research report.

At most 50 lessons are stored in `<workspace>/.kratos/recovery_memory.json`, created after the first verified recovery. Later agent requests recall up to three relevant lessons for the current platform. Memory survives restarts and stays local to that workspace. Current evidence, permissions, and completion checks still govern execution.

Inside the terminal CLI:

```text
/lessons
/lessons clear
```

The first command displays verified lessons and their storage location. The second removes this workspace's recovery memory. Both web and CLI agent runs use the same store when launched with the same workspace. Restart the agent process to load the new implementation:

```powershell
uv run --no-sync kratos-studio run --cli --workspace .
```

The system prompt uses prose rules. Its shared speech rule requests a paired `[[speak]]...[[/speak]]` summary for the final answer unless the user asks for silence or text only. A marked acknowledgement can be spoken before tools execute, once per turn. Failed completion checks replace a model's success claim with an incomplete-task spoken summary.

## Current limits

The import command checks the default launcher ports before running, but the operator must stop any Studio instance started on custom ports too. Live external provider and webhook behavior still needs configured credentials and explicit validation. See `WORK_LOG.md` for implementation status and `FEATURES.md` for the source inventory.
