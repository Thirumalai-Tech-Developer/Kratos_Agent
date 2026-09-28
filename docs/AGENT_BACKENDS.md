# Kratos SDK and agent runtime

## One reasoning path

The installed `kratos_agent.sdk` package is the first-party model SDK. It implements the existing local gateway contract at `/v1/chat/completions`; it does not wrap or install a third-party model-provider SDK.

| Public API | Purpose |
| --- | --- |
| `KratosClient` | Non-streaming and SSE chat completions, typed tool calls, error classification, and bounded retries to the same configured endpoint/model. |
| `KratosCompletion` | Completion text, tool calls, finish reason, and usage. |
| `KratosToolCall` | Tool-call ID, name, and JSON arguments. |
| `KratosAgent` | High-level `run`, restricted `run_chat`, and guarded tool registration. |

The endpoint is derived from `KRATOS_BASE_URL` (default `http://127.0.0.1:20128/v1`) or `KRATOS_CHAT_ENDPOINT`. The reasoning model comes only from `KRATOS_MODEL`. No default model ID is guessed, and a request for another model is rejected. A transport retry resends to the same Kratos endpoint and model; a persistent failure is returned visibly to the caller.

## Execution flow

```text
User request
  -> context and harness
  -> KratosClient completion
  -> validated Kratos tool calls
  -> permission and risk policy
  -> local or MCP tool execution
  -> evidence collection
  -> Kratos continuation or final response
```

`KratosAgent.register_tool()` inserts a JSON-schema `ToolSpec` into the runtime's `ToolRegistry`. It does not bypass validation, workspace boundaries, approval mode, consequence policy, or verification.

## Explicitly separate output services

Gemini Live is a speech renderer only. Its session has no tool declarations and receives no microphone, camera, or screen media. Only a paired `[[speak]]...[[/speak]]` phrase reaches it. Windows System.Speech performs local speech recognition, which routes recognized text into the Kratos agent. Windows SAPI is the local speech-output fallback.

The computer-use server and OpenPets server are MCP tools. MCP extends what Kratos can do; it does not change which model reasons or owns the execution loop.

## Failure behavior

- Missing `KRATOS_MODEL`: fail before sending a completion request.
- Gateway timeout, authentication error, rate limit, or server error: classify and return the failure; only retry eligible transient errors against the same model/endpoint.
- Gemini speech outage: the Kratos task still finishes and its text remains available; marked text can use local SAPI.
- MCP server outage: that server reports unavailable while the Kratos runtime remains available.
