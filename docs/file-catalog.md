# File catalog

Use [`CODEBASE_MAP.md`](CODEBASE_MAP.md) for the active runtime areas and [`architecture.md`](architecture.md) for the request path.

| Path | Description |
| --- | --- |
| `src/kratos_agent/sdk/client.py` | Kratos gateway HTTP/SSE implementation and typed response parsing. |
| `src/kratos_agent/sdk/agent.py` | Public application agent facade. |
| `src/kratos_agent/brain/config.py` | Gateway URL, exact model ID, credentials, timeout, and retry configuration. |
| `src/kratos_agent/core/agent_loop.py` | Planning, tool calls, continuation, and completion verification. |
| `src/kratos_agent/core/tool_runtime.py` | Tool registry, validation, permission, and execution behavior. |
| `src/kratos_agent/core/risk_policy.py` | Consequence classification and direct-request/target checks. |
| `src/kratos_agent/core/verification_manager.py` | Outcome evidence evaluation. |
| `src/kratos_agent/core/mcp_runtime.py` | MCP servers, lifecycle, and tool registration. |
| `src/kratos_agent/core/harness/` | Harness kernel, presets, and runtime plugins. |
| `src/kratos_agent/live/` | Local speech input, optional Gemini speech output, and local screen/camera capture. |
| `src/kratos_agent/output/speech_directives.py` | Fail-closed speech tag parsing and streaming display filter. |
| `openpets/kratos-companion/` | OpenPets plugin implementation and setup instructions. |
| `kratos_agent.spec`, `build_exe.py`, `build.bat`, `build_exe.ps1` | Locked PyInstaller build and Windows entry points; the build output includes the OpenPets plugin beside the executable. |
| `.env.example` | Safe template for the single Kratos reasoning model and optional speech/MCP settings. |
