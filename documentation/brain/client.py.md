# Subsystem: Brain & Gateway Integration
## Module: `kratos_agent.brain.client`

Source File: [`src/kratos_agent/brain/client.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/client.py)

---

### 1. Architectural Purpose & Overview

`client.py` provides the raw HTTP client layer (`BrainClient` / `OmnirouteClient`) responsible for communicating with inference gateways. It implements resilient network policies:
1. **Zero-Proxy Enforcement (`trust_env=False`)**: Guarantees requests are not redirected through corporate or system proxies, avoiding proxy latency and certificate mismatches.
2. **Connection Pooling**: Utilizes custom `HTTPAdapter` instances configured for persistent keep-alive connections across requests (`pool_connections=10`, `pool_maxsize=20`).
3. **OpenAI Protocol Envelope Construction**: Serializes messages, system instructions, tool definitions, and tool call histories into compliant schemas.
4. **SSE Streaming Engine**: Consumes Server-Sent Events line-by-line, handling partial chunks, reasoning tokens (`reasoning_content` from DeepSeek/thinking models), and tool call fragment assembly.
5. **Adaptive Retry with Exponential Backoff**: Automatically handles transient network dropouts, HTTP 429 rate limits, and 5xx gateway faults.
6. **Telemetry & Latency Tracking**: Records round-trip time, time-to-first-token (TTFT), and token generation rates into `latency_tracker`.

---

### 2. Class: `BrainClient` (alias: `OmnirouteClient`)

#### Initialization
```python
BrainClient(endpoint_url: str | None = None)
```
- **`endpoint_url`** (`str | None`, default: `None`): Target chat completions URL (e.g. `http://127.0.0.1:20128/v1/chat/completions`). If `None`, resolved via `get_endpoint_url()`.

#### Properties
- **`session`** (`requests.Session`):
  Lazy-initialized HTTP session. Configured with:
  - `trust_env = False`
  - Mounted HTTPAdapter with `pool_connections=10`, `pool_maxsize=20`, `max_retries=0` (retries are orchestrated at application layer).

---

### 3. Methods & Technical Signatures

#### `build_envelope(...) -> dict[str, Any]`
```python
def build_envelope(
    self,
    model: str,
    messages: list[dict[str, Any]],
    system_instruction: str | None = None,
    stream: bool = True,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]
```
Constructs a normalized OpenAI-compatible payload.
- **Parameters**:
  - `model` (`str`): Model identifier.
  - `messages` (`list[dict[str, Any]]`): List of message dictionaries containing `role` and `content`.
  - `system_instruction` (`str | None`, default: `None`): Optional system prompt inserted at the head of the message history.
  - `stream` (`bool`, default: `True`): Toggles SSE streaming mode.
  - `tools` (`list[dict[str, Any]] | None`, default: `None`): List of OpenAI-format tool definitions (`{"type": "function", "function": {...}}`).
- **Returns**: `dict[str, Any]` - JSON payload ready for `requests.post`.
- **Key Behaviors**:
  - Automatically translates `"developer"` role into `"system"`.
  - Normalizes assistant messages that include raw tool calls (`call_id`, `name`, `args`) into OpenAI standard `tool_calls` structure.
  - Sets `content` to `None` if the message only contains tool calls.

---

#### `generate(...) -> str`
```python
def generate(
    self,
    model: str,
    messages: list[dict[str, Any]],
    system_instruction: str | None = None,
    stream: bool = False,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> str
```
Executes a synchronous request to completion and returns the final generated text.
- **Parameters**:
  - `model` (`str`): Model ID.
  - `messages` (`list[dict[str, Any]]`): Conversation history.
  - `system_instruction` (`str | None`): System prompt.
  - `stream` (`bool`, default: `False`): When `True`, streams internally and concatenates the output.
  - `max_retries` (`int | None`): Maximum retry attempts. Defaults to `get_max_retries()` (default: 2).
  - `timeout` (`float | None`): Per-request socket timeout in seconds. Defaults to `get_request_timeout()` (default: 60s).
- **Returns**: `str` - Completed assistant response content.
- **Error Handling**: Catches connection drops, timeouts, 429 rate limits, and 5xx errors, executing exponential backoff (`delay = 2 ** attempt`). Translates HTTP status codes into typed domain errors (`BrainRateLimitError`, `BrainServerError`, etc.).

---

#### `stream_chat(...) -> Iterator[dict[str, Any]]`
```python
def stream_chat(
    self,
    model: str,
    messages: list[dict[str, Any]],
    system_instruction: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
) -> Iterator[dict[str, Any]]
```
Streams responses using Server-Sent Events (SSE).
- **Parameters**:
  - `model` (`str`): Model ID.
  - `messages` (`list[dict[str, Any]]`): Conversation history.
  - `system_instruction` (`str | None`): System prompt.
  - `tools` (`list[dict[str, Any]] | None`): OpenAI-format tool definitions.
  - `timeout` (`float | None`): Timeout in seconds.
- **Yields**: `dict[str, Any]` representing streamed deltas:
  ```json
  {
    "type": "content" | "reasoning" | "tool_call_delta" | "usage",
    "content": "delta text",
    "tool_calls": [...]
  }
  ```
- **Stream Processing**:
  - Strips `data: ` prefixes from SSE lines.
  - Ignores keep-alive heartbeats (`: ping` or comments).
  - Terminates gracefully when receiving `data: [DONE]`.
  - Captures reasoning tokens emitted in `delta.reasoning_content` (DeepSeek R1 / thinking models).

---

### 4. Error Hierarchy

All client errors inherit from `BrainError`:
```
BrainError (Base Exception)
├── BrainConnectionError (Network unreachable, DNS failure)
├── BrainTimeoutError (Socket or gateway read timeout)
├── BrainRateLimitError (HTTP 429 Too Many Requests)
├── BrainBadRequestError (HTTP 400 Malformed payload)
├── BrainNotFoundError (HTTP 404 Model or route missing)
└── BrainServerError (HTTP 500/502/503 Gateway failure)
```
