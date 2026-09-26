# Subsystem: Brain & Gateway Integration
## Module: `kratos_agent.brain.config`

Source File: [`src/kratos_agent/brain/config.py`](file:///c:/Users/thiru/Documents/Kratos_Agent/src/kratos_agent/brain/config.py)

---

### 1. Architectural Purpose & Overview

`config.py` centralizes all environment variables, fallback URL derivations, authentication headers, error hierarchies, and model catalog caching for Kratos' inference subsystems.

Key features:
- **Environment Fallback Precedence**: Supports multi-prefix configuration (`OMNI_*`, `BRAIN_*`, `KRATOS_*`, standard `OPENAI_*`).
- **Endpoint Auto-Resolution**: Automatically normalizes base URLs into `/chat/completions` and `/models` paths.
- **Model Catalog Discovery & Caching**: Queries `/v1/models` dynamically and caches results for 30 seconds (`_CACHE_TTL_SECONDS = 30.0`).
- **Standardized Exception System**: Defines domain-specific network and gateway exceptions.

---

### 2. Default Constants

| Constant | Default Value | Description |
|---|---|---|
| `DEFAULT_BASE_URL` | `"http://127.0.0.1:20128/v1"` | Gateway base URL |
| `DEFAULT_CHAT_ENDPOINT` | `"http://127.0.0.1:20128/v1/chat/completions"` | Chat completions endpoint |
| `DEFAULT_MODEL_ENDPOINT` | `"http://127.0.0.1:20128/v1/models"` | Model catalog endpoint |
| `DEFAULT_MODEL` | `"antigravity/gemini-3.7-flash-high"` | Default inference model |
| `DEFAULT_TIMEOUT_SECONDS` | `60.0` | Socket read timeout |
| `DEFAULT_MAX_RETRIES` | `2` | Number of gateway retry attempts |
| `_CACHE_TTL_SECONDS` | `30.0` | TTL for model listing cache |

---

### 3. Exported Functions & Signatures

#### `get_api_key(explicit_key: str | None = None) -> str`
Resolves API token from explicit arguments or environment variables in descending precedence:
1. `explicit_key`
2. `os.getenv("OMNI_KEY")`
3. `os.getenv("BRAIN_KEY")`
4. `os.getenv("KRATOS_API_KEY")`
5. `os.getenv("API_KEY")`
6. `os.getenv("OPENAI_API_KEY")`
7. Empty string `""`

---

#### `authenticate(explicit_key: str | None = None) -> dict[str, str]`
Generates HTTP request headers containing `Content-Type: application/json`, `Connection: Keep-Alive`, and optional `Authorization: Bearer <key>`.

---

#### `get_base_url() -> str`
Derives the base URL from `BRAIN_BASE_URL`, `CHAT_BASE_URL`, `OMNIROUTE_BASE_URL`, or `DEFAULT_BASE_URL`. Strips trailing slashes.

---

#### `get_endpoint_url() -> str`
Constructs the full chat completions URL:
1. Checks direct overrides (`CHAT_ENDPOINT`, `BRAIN_CHAT_URL`, `KRATOS_API_URL`, `OMNIROUTE_CHAT_URL`).
2. If absent, appends `/chat/completions` to `get_base_url()`.

---

#### `get_model_endpoint_url() -> str`
Constructs the full model listing URL:
1. Checks direct overrides (`MODEL_ENDPOINT`, `BRAIN_MODEL_URL`).
2. If absent, appends `/models` to `get_base_url()`.

---

#### `get_default_model() -> str` (alias: `get_model()`)
Resolves configured model identifier from `BRAIN_MODEL`, `OMNIROUTE_MODEL`, `KRATOS_MODEL`, or `DEFAULT_MODEL`.

---

#### `fetch_models(force_refresh: bool = False) -> list[str]`
Discovers available models from the inference gateway.
- Caches model list in memory for 30 seconds.
- Queries `get_model_endpoint_url()` with `authenticate()`.
- Parses OpenAI-compliant response: `{"data": [{"id": "model-1"}, ...]}`.
- Falls back to `[get_default_model()]` if gateway is unreachable.

---

#### `get_available_models() -> list[str]`
Convenience wrapper around `fetch_models()`.
