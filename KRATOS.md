# ⚔️ Kratos Project Memory

![Kratos Agent](https://i.imgur.com/uQfWb3t.jpeg)

**Project Scope:** The workspace root containing this file.

This user-managed file supplies persistent project instructions across sessions. Loading it does not rewrite it.
Add any context, architecture decisions, or configuration notes here.

### Runtime boundaries
- All reasoning and agent tool decisions use the explicitly configured Kratos model through the local Kratos gateway.
- Gemini is an optional speech renderer for text explicitly marked with `[[speak]]...[[/speak]]`; it does not receive reasoning prompts or tools.
- Desktop and browser capabilities are provided through MCP and pass through the Kratos permission and evidence checks.


### Project architecture and workflow

- The Python runtime in `src/kratos_agent/main.py` composes instructions, model selection, tools, sessions, and the agent loop. Core orchestration and evidence checks live in `src/kratos_agent/core`.
- The SDK in `src/kratos_agent/sdk` carries the selected model and cancellation through the local gateway. `services/omniroute` routes gateway and supported web model requests.
- The workspace UI is in `frontend`; the Python web server exposes its runtime state and task events.
- The browser extension collects and refreshes protected session cookies. Model requests use the local executor; normal browser sign-in and model access are separate checks.
- Keep project changes focused, preserve existing user changes, and inspect real tool results before reporting completion.
- Start local development from this root with `uv run --no-sync kratos-studio run --dev --workspace . --no-browser`. Run relevant existing Python checks with `uv run pytest <focused test paths> -q`. Build the UI from `frontend` with `npm run build`.
- Use the configured model and keep conversation continuation stable. Send project-guidance changes once on the next message; do not repeat a full system prompt on each website turn.
- Treat this file as project guidance under the current user request. It does not override permissions, verified evidence, or higher-priority runtime instructions.
