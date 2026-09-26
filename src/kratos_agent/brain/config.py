from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "http://127.0.0.1:20128/v1"
DEFAULT_CHAT_ENDPOINT = "http://127.0.0.1:20128/v1/chat/completions"
DEFAULT_MODEL_ENDPOINT = "http://127.0.0.1:20128/v1/models"
DEFAULT_MODEL = "antigravity/gemini-3.7-flash-high"
DEFAULT_TIMEOUT_SECONDS: float = 60.0
DEFAULT_MAX_RETRIES: int = 2

_cached_models: list[str] = []
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS: float = 30.0


def get_api_key(explicit_key: str | None = None) -> str:
    """Returns configured API key from argument or environment."""
    if explicit_key:
        return explicit_key
    return (
        os.getenv("OMNI_KEY")
        or os.getenv("BRAIN_KEY")
        or os.getenv("KRATOS_API_KEY")
        or os.getenv("API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def authenticate(explicit_key: str | None = None) -> dict[str, str]:
    key = explicit_key or get_api_key()
    headers = {
        "Content-Type": "application/json",
        "Connection": "Keep-Alive"
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def get_base_url() -> str:
    """Returns the base URL for the Brain API."""
    return (
        os.getenv("BRAIN_BASE_URL")
        or os.getenv("CHAT_BASE_URL")
        or os.getenv("OMNIROUTE_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def get_endpoint_url() -> str:
    """Returns the chat completions endpoint URL."""
    direct_url = (
        os.getenv("CHAT_ENDPOINT")
        or os.getenv("BRAIN_CHAT_URL")
        or os.getenv("KRATOS_API_URL")
        or os.getenv("OMNIROUTE_CHAT_URL")
    )
    if direct_url:
        return direct_url
    base = get_base_url()
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def get_model_endpoint_url() -> str:
    """Returns the model listing endpoint URL."""
    direct_url = (
        os.getenv("MODEL_ENDPOINT")
        or os.getenv("BRAIN_MODEL_URL")
    )
    if direct_url:
        return direct_url
    base = get_base_url()
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def get_default_model() -> str:
    """Returns the configured or default model name."""
    return (
        os.getenv("BRAIN_MODEL")
        or os.getenv("OMNIROUTE_MODEL")
        or os.getenv("KRATOS_MODEL")
        or DEFAULT_MODEL
    )


def _extract_model_ids(payload: Any) -> list[str]:
    """Extracts unique model IDs from various LLM gateway response schemas."""
    raw_list: list[Any] = []
    if isinstance(payload, list):
        raw_list = payload
    elif isinstance(payload, dict):
        if "data" in payload and isinstance(payload["data"], list):
            raw_list = payload["data"]
        elif "models" in payload and isinstance(payload["models"], list):
            raw_list = payload["models"]
        elif "items" in payload and isinstance(payload["items"], list):
            raw_list = payload["items"]
        elif "id" in payload:
            raw_list = [payload]

    model_ids: list[str] = []
    for item in raw_list:
        mid = ""
        if isinstance(item, str):
            mid = item.strip()
        elif isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        if mid and mid not in model_ids:
            model_ids.append(mid)
    return model_ids


def get_model(
    endpoint: str | None = None,
    timeout: float = 3.0,
    refresh: bool = False,
) -> list[str]:
    """Dynamically fetches available models from the active model endpoint or cache."""
    global _cached_models, _cache_timestamp

    target_endpoint = endpoint or get_model_endpoint_url()
    now = time.time()

    # Use cache if fresh and not forcing refresh (and using default endpoint)
    if not refresh and endpoint is None and _cached_models and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        return list(_cached_models)

    session = requests.Session()
    session.trust_env = False
    header = authenticate()
    try:
        result = session.get(target_endpoint, headers=header, timeout=timeout)
        if result.status_code == 200:
            result_json = result.json()
            model_list = _extract_model_ids(result_json)
            if model_list:
                _cached_models = list(model_list)
                _cache_timestamp = now
                if "PUBLIC_MODELS" in globals() and isinstance(PUBLIC_MODELS, list):
                    PUBLIC_MODELS.clear()
                    PUBLIC_MODELS.extend(model_list)
                return list(model_list)
    except Exception as exc:
        logger.debug("Operation error suppressed: %s", exc)

    # If fetch failed, fall back to cached models if available
    if _cached_models:
        return list(_cached_models)

    # Dynamic fallback: configured default model from environment
    default_model = get_default_model()
    return [default_model] if default_model else []


def fetch_models(endpoint: str | None = None, timeout: float = 3.0, refresh: bool = False) -> list[str]:
    """Alias for get_model."""
    return get_model(endpoint=endpoint, timeout=timeout, refresh=refresh)


def get_available_models(refresh: bool = False, timeout: float = 3.0) -> list[str]:
    """Fetches currently available models dynamically from the active gateway."""
    return get_model(refresh=refresh, timeout=timeout)


PUBLIC_MODELS: list[str] = []


def get_normal_mode_model() -> str:
    """Returns the configured model name for normal chat mode."""
    return os.getenv("NORMAL_MODE_MODEL") or "deepseek-web/deepseek-v4-pro"


def get_request_timeout() -> float:
    """Returns the request timeout in seconds."""
    raw = (
        os.getenv("BRAIN_TIMEOUT")
        or os.getenv("OMNIROUTE_TIMEOUT")
        or os.getenv("KRATOS_TIMEOUT")
    )
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_TIMEOUT_SECONDS


def get_max_retries() -> int:
    """Returns the maximum retry attempts for transient errors."""
    raw = (
        os.getenv("BRAIN_MAX_RETRIES")
        or os.getenv("OMNIROUTE_MAX_RETRIES")
        or os.getenv("KRATOS_MAX_RETRIES")
    )
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_MAX_RETRIES


# Compatibility alias
DEFAULT_OMNIROUTE_URL = DEFAULT_CHAT_ENDPOINT


class BrainError(Exception):
    """Base error for Brain API calls."""


class BrainConnectionError(BrainError):
    """Raised when the Brain endpoint is unreachable."""


class BrainTimeoutError(BrainError):
    """Raised when a Brain request times out."""


class BrainRateLimitError(BrainError):
    """Raised when the endpoint returns HTTP 429."""


class BrainBadRequestError(BrainError):
    """Raised when the endpoint returns HTTP 400."""


class BrainNotFoundError(BrainError):
    """Raised when the endpoint or model is not found (HTTP 404)."""


class BrainServerError(BrainError):
    """Raised when the Brain server returns HTTP 5xx."""


# Backward compatibility aliases
OmnirouteError = BrainError
OmnirouteConnectionError = BrainConnectionError
OmnirouteTimeoutError = BrainTimeoutError
OmnirouteRateLimitError = BrainRateLimitError
OmnirouteBadRequestError = BrainBadRequestError
OmnirouteNotFoundError = BrainNotFoundError
OmnirouteServerError = BrainServerError


# ==============================================================================
# Headroom Context Compression Configuration
# ==============================================================================

def is_headroom_enabled() -> bool:
    """Returns True if Headroom context compression is enabled (default: True)."""
    raw = os.getenv("HEADROOM_ENABLED", "true").lower().strip()
    return raw in ("true", "1", "yes", "on")


def get_headroom_model() -> str:
    """Returns the tokenizer model for Headroom token counting (default: gpt-4o)."""
    return os.getenv("HEADROOM_MODEL", "gpt-4o").strip()


def get_headroom_proxy_port() -> int | None:
    """Returns the Headroom proxy port if configured (e.g. 8787)."""
    raw = os.getenv("HEADROOM_PROXY_PORT")
    if raw:
        try:
            return int(raw.strip())
        except ValueError:
            pass
    return None


# ==============================================================================
# Parallel Execution Configuration
# ==============================================================================

def is_parallel_execution_enabled() -> bool:
    """Returns True if concurrent/parallel tool execution is enabled (default: True)."""
    raw = os.getenv("KRATOS_PARALLEL_EXECUTION", "true").lower().strip()
    return raw in ("true", "1", "yes", "on")


def get_max_parallel_workers() -> int:
    """Returns the maximum worker threads for parallel tool execution (default: 8)."""
    raw = os.getenv("KRATOS_MAX_PARALLEL_WORKERS", "8").strip()
    try:
        val = int(raw)
        return max(1, min(val, 32))
    except ValueError:
        return 8


