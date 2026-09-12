# Brain and Model Gateway Reference

## Configuration module: `src/kratos_agent/brain/config.py`

Constants:

- `DEFAULT_BASE_URL`, `DEFAULT_CHAT_ENDPOINT`, `DEFAULT_MODEL_ENDPOINT`: local gateway defaults at port 20128.
- `DEFAULT_MODEL`: `antigravity/gemini-3.7-flash-high`.
- `DEFAULT_TIMEOUT_SECONDS`: `60.0`.
- `DEFAULT_MAX_RETRIES`: `2`.
- `DEFAULT_PUBLIC_MODELS`: fallback model identifiers.
- `PUBLIC_MODELS`: model list resolved at import time by `get_model()`.

Functions:

- `get_api_key(explicit_key=None) -> str`: returns the explicit key or the first non-empty value from `OMNI_KEY`, `BRAIN_KEY`, `KRATOS_API_KEY`, and `OPENAI_API_KEY`.
- `authenticate(explicit_key=None) -> dict[str, str]`: creates JSON/keep-alive headers and adds a Bearer header when a key exists.
- `get_model(endpoint=None, timeout=3.0) -> list[str]`: performs a proxy-free GET to the model endpoint, accepts OpenAI-style `{data: [{id}]}` or string entries, and falls back to `DEFAULT_PUBLIC_MODELS` on any failure.
- `fetch_models(endpoint=None, timeout=3.0)`: compatibility alias for `get_model`.
- `get_base_url() -> str`: resolves `BRAIN_BASE_URL`, `CHAT_BASE_URL`, `OMNIROUTE_BASE_URL`, then the local default.
- `get_endpoint_url() -> str`: resolves a direct chat endpoint or appends `/chat/completions` to the base URL.
- `get_model_endpoint_url() -> str`: resolves a direct model endpoint or appends `/models`.
- `get_default_model() -> str`: resolves `BRAIN_MODEL`, `OMNIROUTE_MODEL`, `KRATOS_MODEL`, then the default.
- `get_normal_mode_model() -> str`: resolves `NORMAL_MODE_MODEL`, otherwise `deepseek-web/deepseek-v4-pro`.
- `get_request_timeout() -> float`: parses timeout environment variables, clamps valid values to at least one second, and falls back to 60 seconds.
- `get_max_retries() -> int`: parses retry variables, clamps to zero or greater, and falls back to two.

Exception hierarchy: `BrainError` is the base class; `BrainConnectionError`, `BrainTimeoutError`, `BrainRateLimitError`, `BrainBadRequestError`, `BrainNotFoundError`, and `BrainServerError` classify transport/status failures. `Omniroute*` names are compatibility aliases.

## HTTP client: `client.py`

`BrainClient(endpoint_url=None)` lazily creates a `requests.Session` with `trust_env=False`, connection pooling, and no requests-level retry policy.

- `build_envelope(model, messages, system_instruction=None, stream=True, tools=None) -> dict`: converts internal messages to an OpenAI-compatible payload. It normalizes system/developer roles, assistant tool metadata, tool results, list content, and tool schemas.
- `complete(model, messages, system_instruction=None, tools=None, max_retries=None, timeout=None, task_id="", stream=True, on_chunk=None) -> tuple[str, list[dict]]`: sends a request, handles streaming/non-streaming responses, reports chunks through `on_chunk`, tracks latency/TTFT, retries transient failures, and returns text plus normalized tool calls.
- `generate(model=None, messages=None, system_instruction=None, tools=None, stream=False, on_chunk=None, **kwargs)`: compatibility wrapper around completion behavior.
- `session` property: creates the configured HTTP session once.

`OmnirouteClient` preserves the older client name and behavior for callers that still import it.

## LangChain adapter: `brain.py` and `chat_model.py`

- `get_http_client() -> httpx.Client`: returns an `httpx.Client(trust_env=False)`.
- `create_brain_llm(model=None, base_url=None, api_key=None) -> ChatOpenAI`: creates a LangChain OpenAI-compatible chat model, using `kratos-brain-key` only when no key is configured.
- `get_agent_response(query, model=None, endpoint_url=None) -> str`: performs one non-streaming user query through `BrainClient`.

`BrainChatModel(model=None, endpoint_url=None, **kwargs)` implements LangChain's `BaseChatModel` boundary and delegates to `BrainClient`. It supports `_generate` and `_stream` plus `invoke`-compatible message handling. `OmnirouteChatModel` is the compatibility subclass/name.

Tool-call parsing helpers:

- `clean_file_path(fp_str) -> str`: strips raw-string prefixes, quote/hash artifacts, and whitespace.
- `_clean_command_payload(cmd_str) -> str`: removes markdown fences, labels, JSON-like prefixes, and trailing artifacts from commands.
- `_extract_json_object(text, start_idx)`: balances braces while respecting quoted strings and attempts strict JSON, normalized keys, then a tool-specific fallback.
- `_fallback_extract_tool_call(text)`: recovers `edit_file`, `write_file`, and `run_terminal_command` calls when model JSON is malformed.
- `extract_tool_calls_from_text(text) -> tuple[str, list[dict]]`: recognizes Harmony/ChatML, `<tool_call>` XML, `call:name{json}`, and markdown/JSON forms; removes recognized call spans from visible text and returns calls as `{name, args}`.

The valid parser tool names include workspace tools, browser/search tools, memory tools, diagnostics, and Python execution names. The actual local registry is authoritative for executable tools.
