# Kratos gateway and SDK reference

## Configuration

The first-party client posts to the existing local gateway's OpenAI-compatible chat-completions endpoint. Defaults and environment resolution live in `src/kratos_agent/brain/config.py`.

| Variable | Behavior |
| --- | --- |
| `KRATOS_BASE_URL` | Gateway API root; defaults to `http://127.0.0.1:20128/v1`. |
| `KRATOS_MODEL` | Required exact reasoning model ID. No alternate model is selected. |
| `KRATOS_API_KEY` | Optional gateway credential when authentication is enabled. |
| `KRATOS_TIMEOUT` | Request timeout in seconds; defaults to 60. |
| `KRATOS_MAX_RETRIES` | Retries for eligible transient failures; defaults to 2. Retries keep the same endpoint and model. |

The model catalog is consulted only to confirm that the configured model ID is available. It is never used to choose another model. If `KRATOS_MODEL` is empty, completion fails before a request is sent.

## Public SDK

Import the first-party API from `kratos_agent.sdk`:

```python
from kratos_agent.sdk import KratosAgent, KratosClient
```

`KratosClient.complete(payload, stream=None, on_chunk=None, ...)` returns a `KratosCompletion`. A completion contains text, `KratosToolCall` objects, finish reason, and usage. The streaming parser reads server-sent events and assembles fragmented tool-call IDs, names, and JSON arguments. Malformed tool arguments fail as a visible protocol error.

`KratosAgent.run(prompt)` sends a task through the application execution loop. `run_chat(prompt)` uses restricted chat. `register_tool(...)` adds a schema and handler to the same permission-controlled registry used by the application.

## Gateway failure behavior

HTTP errors are mapped to typed `BrainError` subclasses for existing app diagnostics. Transient connection, timeout, rate-limit, and server errors may be retried with backoff. Authentication, invalid request, missing endpoint/model, malformed response, or exhausted retries fail to the caller. The SDK never changes the model or endpoint to recover.

The `BrainClient` class remains as a compatibility facade for application modules. All transport and parsing are delegated to `KratosClient`.
