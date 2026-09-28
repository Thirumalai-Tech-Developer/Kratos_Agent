# Python API reference

## Public SDK

```python
from kratos_agent.sdk import KratosAgent, KratosClient, KratosCompletion, KratosToolCall
```

- `KratosClient.complete(payload, ...) -> KratosCompletion` sends one request to the configured local gateway.
- `KratosCompletion` contains `text`, `tool_calls`, `finish_reason`, and usage data.
- `KratosToolCall` contains `id`, `name`, and decoded JSON `arguments`.
- `KratosAgent.run(prompt)` executes through the full guarded agent loop.
- `KratosAgent.run_chat(prompt)` runs without autonomous tool execution.
- `KratosAgent.register_tool(...)` registers a schema and callable with the runtime tool registry.

`KRATOS_MODEL` locks all reasoning calls to one exact ID. See [`brain-reference.md`](brain-reference.md) for transport/configuration details.

## Agent internals

- `core/agent_loop.py`: model/tool continuation loop, speech marker extraction, task planning, and completion gates.
- `core/context_pipeline.py`: instruction assembly, history shaping, schema inclusion, and token budgeting.
- `core/runtime_contracts.py`: tool specs/results, chat messages, event contracts, and permissions.
- `core/tool_runtime.py`: schemas, argument validation, execution permissions, and result conversion.
- `core/risk_policy.py`: high-consequence action and explicit-target assessment.
- `core/verification_manager.py`: assertions, evidence aggregation, and verification verdicts.
- `core/mcp_runtime.py`: configured MCP server startup and tool discovery.
- `core/harness/`: execution presets and first-party runtime plugins.
- `output/speech_directives.py`: paired `[[speak]]...[[/speak]]` parsing; malformed directives fail closed.

## Live voice

`live/runtime.py` routes local Windows speech recognition text into the Kratos handler. Its Gemini session is a text-to-speech output transport with no tools or incoming media. `output/voice.py` sanitizes explicitly approved phrases before speech playback.
