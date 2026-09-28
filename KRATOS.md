# ⚔️ Kratos Project Memory

![Kratos Agent](https://i.imgur.com/uQfWb3t.jpeg)

**Project Path:** C:\Users\thiru\Documents\Kratos_Agent

This file is automatically managed by Kratos. It acts as persistent project memory across sessions.
Add any context, architecture decisions, or configuration notes here.

### Runtime boundaries
- All reasoning and agent tool decisions use the explicitly configured Kratos model through the local Kratos gateway.
- Gemini is an optional speech renderer for text explicitly marked with `[[speak]]...[[/speak]]`; it does not receive reasoning prompts or tools.
- Desktop and browser capabilities are provided through MCP and pass through the Kratos permission and evidence checks.
