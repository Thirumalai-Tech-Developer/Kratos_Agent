# Subsystem: Brain & Gateway Integration
## Module: `kratos_agent.brain.brain`

Source File: [`src/kratos_agent/brain/brain.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/brain.py)

---

### 1. Architectural Purpose & Overview

The `brain.py` module acts as the primary factory and lightweight gateway adapter for LLM generation within Kratos. It bridges low-level HTTP transport and high-level LangChain model abstractions to interface with OpenAI-compatible inference servers, OmniRoute gateways, or self-hosted LLM clusters.

Key responsibilities:
- **Proxy-Bypassing HTTP Client**: Produces an isolated `httpx.Client` configured with `trust_env=False` to prevent corporate or system HTTP proxies from intercepting or slowing local LLM traffic.
- **LangChain Integration Factory**: Constructs ready-to-use `ChatOpenAI` instances configured specifically for Kratos' model routing and endpoints.
- **Synchronous Agent Generation Utility**: Provides an immediate one-shot query execution function (`get_agent_response`) that leverages `BrainClient` for rapid utility queries without requiring an active agent loop.

```
                    ┌───────────────────────────┐
                    │      Caller / Client      │
                    │ (CLI, AgentLoop, Planner) │
                    └─────────────┬─────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          │                                               │
          ▼                                               ▼
┌───────────────────┐                           ┌───────────────────┐
│ create_brain_llm  │                           │get_agent_response │
└─────────┬─────────┘                           └─────────┬─────────┘
          │                                               │
          ▼                                               ▼
┌───────────────────┐                           ┌───────────────────┐
│ChatOpenAI Instance│                           │    BrainClient    │
│  (LangChain Chat) │                           │ (Raw HTTP Client) │
└─────────┬─────────┘                           └─────────┬─────────┘
          │                                               │
          └───────────────────────┬───────────────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │      get_http_client      │
                    │    (httpx.Client with     │
                    │     trust_env=False)      │
                    └─────────────┬─────────────┘
                                  ▼
                    ┌───────────────────────────┐
                    │  Brain / Gateway Endpoint │
                    │ (Default: 127.0.0.1:20128)│
                    └───────────────────────────┘
```

---

### 2. Exported Functions & Signatures

#### `get_http_client() -> httpx.Client`

Creates and returns a dedicated HTTP client instance explicitly configured to ignore OS environment variables for proxies.

- **Arguments**: None.
- **Returns**: `httpx.Client` instance initialized with `trust_env=False`.
- **Purpose**: Prevents unintended interception from `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` variables configured in corporate or developer environments. Ensures high-throughput, low-latency communication directly to the LLM endpoint.
- **Example Usage**:
  ```python
  from kratos_agent.brain.brain import get_http_client

  client = get_http_client()
  response = client.get("http://127.0.0.1:20128/v1/models")
  ```

---

#### `create_brain_llm(model: str | None = None, base_url: str | None = None, api_key: str | None = None) -> ChatOpenAI`

Constructs and returns an instantiated LangChain `ChatOpenAI` chat model targeting the Kratos Brain endpoint.

- **Parameters**:
  - `model` (`str | None`, default: `None`): The identifier of the model to use (e.g., `antigravity/gemini-3.7-flash-high`, `deepseek/deepseek-chat`). If `None`, resolved via `get_default_model()` from environment variables (`BRAIN_MODEL`, `OMNIROUTE_MODEL`, `KRATOS_MODEL`, or default constant).
  - `base_url` (`str | None`, default: `None`): The base URL of the API gateway (e.g., `http://127.0.0.1:20128/v1`). If `None`, resolved via `get_base_url()` from environment variables (`BRAIN_BASE_URL`, `CHAT_BASE_URL`, `OMNIROUTE_BASE_URL`, or default constant). Any trailing slash is automatically stripped.
  - `api_key` (`str | None`, default: `None`): Authorization bearer token. If `None`, resolved via `get_api_key()` from environment variables (`OMNI_KEY`, `BRAIN_KEY`, `KRATOS_API_KEY`, etc.). Defaults to `"kratos-brain-key"` if empty.
- **Returns**: `ChatOpenAI` - A configured LangChain chat model ready for structured generation, tool binding, and streaming.
- **Internal Mechanisms**:
  1. Resolves `target_model` using fallback chain.
  2. Resolves and normalizes `target_base_url`.
  3. Resolves `target_api_key`.
  4. Binds `get_http_client()` to the `http_client` parameter of `ChatOpenAI` to bypass OS proxies.
- **Example Usage**:
  ```python
  from kratos_agent.brain.brain import create_brain_llm

  llm = create_brain_llm(model="deepseek/deepseek-chat")
  response = llm.invoke("Summarize repository status.")
  print(response.content)
  ```

---

#### `get_agent_response(query: str, model: str | None = None, endpoint_url: str | None = None) -> str`

Executes a one-shot synchronous user query to the Brain gateway without setting up an agent loop or LangChain chain.

- **Parameters**:
  - `query` (`str`): The user prompt or instruction to send.
  - `model` (`str | None`, default: `None`): Model ID to execute against. Resolves via `get_default_model()` if `None`.
  - `endpoint_url` (`str | None`, default: `None`): Full chat completions endpoint URL. Resolves via `get_endpoint_url()` if `None`.
- **Returns**: `str` - Raw text content returned by the model.
- **Internal Mechanisms**:
  1. Instantiates a `BrainClient` pointing to `endpoint_url`.
  2. Sends an envelope with `[{"role": "user", "content": query}]` and `stream=False`.
  3. Returns the string content directly.
- **Example Usage**:
  ```python
  from kratos_agent.brain.brain import get_agent_response

  reply = get_agent_response("Explain AST validation in one sentence.")
  print(reply)
  ```

---

### 3. Dependencies & Interactions

- **Internal Imports**:
  - `kratos_agent.brain.client.BrainClient`: Low-level raw HTTP client for direct payload generation.
  - `kratos_agent.brain.config`: Configuration helpers (`get_api_key`, `get_base_url`, `get_default_model`, `get_endpoint_url`).
- **External Imports**:
  - `httpx`: High-performance HTTP client library.
  - `langchain_openai.ChatOpenAI`: LangChain's standard OpenAI-compatible chat model wrapper.
- **Consumed By**:
  - `kratos_agent.core.planner`: Uses `create_brain_llm` to instantiate the decision-making brain.
  - `kratos_agent.core.agent_loop`: Consumes the configured LLM for multi-turn tool calling.
  - `kratos_agent.cli`: Interacts with LLM for tool forging (`/create-tool`) and system queries.
