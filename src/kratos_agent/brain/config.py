from __future__ import annotations

import os
from typing import Dict, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "http://127.0.0.1:20128/v1"
DEFAULT_CHAT_ENDPOINT = "http://127.0.0.1:20128/v1/chat/completions"
DEFAULT_MODEL_ENDPOINT = "http://127.0.0.1:20128/v1/models"
DEFAULT_MODEL = "antigravity/gemini-3.7-flash-high"
DEFAULT_TIMEOUT_SECONDS: float = 60.0
DEFAULT_MAX_RETRIES: int = 2

DEFAULT_PUBLIC_MODELS: List[str] = [
    "antigravity/gemini-3.7-flash-high",
    "antigravity/gpt-oss-120b-medium",
    "gemini-3.7-flash-high",
    "gemini-3.7-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "claude-3-7-sonnet",
    "gpt-4o-mini",
    "ollama-cloud/nemotron-3-super",
    "auto/best-free",
]


def get_api_key(explicit_key: Optional[str] = None) -> str:
    """Returns configured API key from argument or environment."""
    if explicit_key:
        return explicit_key
    return (
        os.getenv("OMNI_KEY")
        or os.getenv("BRAIN_KEY")
        or os.getenv("KRATOS_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def authenticate(explicit_key: Optional[str] = None) -> Dict[str, str]:
    key = explicit_key or get_api_key()
    headers = {
        "Content-Type": "application/json",
        "Connection": "Keep-Alive"
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def get_model(endpoint: Optional[str] = None, timeout: float = 3.0) -> List[str]:
    """Model"""
    target_endpoint = endpoint or os.getenv("MODEL_ENDPOINT") or DEFAULT_MODEL_ENDPOINT
    session = requests.Session()
    session.trust_env = False
    header = authenticate()
    try:
        result = session.get(target_endpoint, headers=header, timeout=timeout)
        if result.status_code == 200:
            result_json = result.json()
            model_list = []
            data = result_json.get("data", [])
            for res in data:
                if isinstance(res, dict) and "id" in res:
                    model_list.append(res["id"])
                elif isinstance(res, str):
                    model_list.append(res)
            if model_list:
                return model_list
    except Exception:
        pass
    return list(DEFAULT_PUBLIC_MODELS)


def fetch_models(endpoint: Optional[str] = None, timeout: float = 3.0) -> List[str]:
    """Alias for get_model."""
    return get_model(endpoint=endpoint, timeout=timeout)


PUBLIC_MODELS = get_model()


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
    pass


class BrainConnectionError(BrainError):
    """Raised when the Brain endpoint is unreachable."""
    pass


class BrainTimeoutError(BrainError):
    """Raised when a Brain request times out."""
    pass


class BrainRateLimitError(BrainError):
    """Raised when the endpoint returns HTTP 429."""
    pass


class BrainBadRequestError(BrainError):
    """Raised when the endpoint returns HTTP 400."""
    pass


class BrainNotFoundError(BrainError):
    """Raised when the endpoint or model is not found (HTTP 404)."""
    pass


class BrainServerError(BrainError):
    """Raised when the Brain server returns HTTP 5xx."""
    pass


# Backward compatibility aliases
OmnirouteError = BrainError
OmnirouteConnectionError = BrainConnectionError
OmnirouteTimeoutError = BrainTimeoutError
OmnirouteRateLimitError = BrainRateLimitError
OmnirouteBadRequestError = BrainBadRequestError
OmnirouteNotFoundError = BrainNotFoundError
OmnirouteServerError = BrainServerError
