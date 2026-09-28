"""Kratos gateway configuration and lazy application adapters."""
from __future__ import annotations

from typing import Any

from .config import (
    DEFAULT_BASE_URL,
    DEFAULT_CHAT_ENDPOINT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_MODEL_ENDPOINT,
    DEFAULT_TIMEOUT_SECONDS,
    BrainBadRequestError,
    BrainConnectionError,
    BrainError,
    BrainNotFoundError,
    BrainRateLimitError,
    BrainServerError,
    BrainTimeoutError,
    authenticate,
    fetch_models,
    get_api_key,
    get_available_models,
    get_base_url,
    get_default_model,
    get_endpoint_url,
    get_max_retries,
    get_model,
    get_model_endpoint_url,
    get_request_timeout,
)


def __getattr__(name: str) -> Any:
    if name == "BrainClient":
        from .client import BrainClient
        return BrainClient
    if name == "get_agent_response":
        from .brain import get_agent_response
        return get_agent_response
    if name in {"KratosClient", "KratosCompletion", "KratosToolCall"}:
        from kratos_agent import sdk
        return getattr(sdk, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEFAULT_BASE_URL", "DEFAULT_CHAT_ENDPOINT", "DEFAULT_MODEL_ENDPOINT", "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS", "DEFAULT_MAX_RETRIES", "BrainError", "BrainConnectionError",
    "BrainTimeoutError", "BrainRateLimitError", "BrainBadRequestError", "BrainNotFoundError",
    "BrainServerError", "authenticate", "fetch_models", "get_api_key", "get_available_models",
    "get_base_url", "get_default_model", "get_endpoint_url", "get_max_retries", "get_model",
    "get_model_endpoint_url", "get_request_timeout", "BrainClient",
    "get_agent_response", "KratosClient", "KratosCompletion", "KratosToolCall",
]
