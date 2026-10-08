# Kratos documentation

These are the maintained references for the current Kratos-only runtime. The repository's retired generated documentation and superseded multi-provider design reports were removed; Git history retains them if needed.

## Runtime and model SDK

- [Architecture](architecture.md): request flow, policy boundaries, and model outage behavior.
- [Kratos SDK and agent runtime](AGENT_BACKENDS.md): public SDK, tool execution, speech boundary, and failures.
- [Gateway and SDK reference](brain-reference.md): configuration, streaming, and error behavior.
- [Python API reference](python-reference.md): public Python interfaces.
- [Agent harness](agent-harness.md): presets, plugins, context, and evidence.
- [Codebase map](CODEBASE_MAP.md): active source directories and responsibilities.

## Tools, safety, and runtime data

- [Computer use](COMPUTER_USE.md): desktop and browser execution.
- [GUI automation](GUI_AUTOMATION.md): UI backends and element confidence.
- [Tools and data](tools-and-data.md): MCP, skills, memory, and data boundaries.
- [Security policy](SECURITY.md): risk and action boundaries.
- [Web API](web-api.md): local Python API and Cloudflare services.
- [AI and ML job applications](JOBS.md): free discovery feeds, applicant profiles, auto-apply and receipts.
- [Cloudflare D1 setup](cloudflare_d1_setup.md): optional database configuration.

## Voice, frontend, and builds

- [Gemini Live](GEMINI_LIVE.md): marked speech output and local speech recognition.
- [Testing and build](testing-and-build.md): development commands and Windows packaging.
- [Frontend reference](frontend-reference.md): React frontend structure and configuration.
