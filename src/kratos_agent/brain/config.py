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
# Compatibility constant for callers that inspect the default. Runtime model
# selection is resolved by get_default_model() from explicit environment values.
DEFAULT_MODEL = ""
DEFAULT_TIMEOUT_SECONDS: float = 60.0
DEFAULT_MAX_RETRIES: int = 2

_cached_models: list[str] = []
_cached_model_details: dict[str, dict[str, Any]] = {}
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS: float = 30.0

PUBLIC_MODELS: list[str] = []


def get_api_key(explicit_key: str | None = None) -> str:
    """Returns configured API key from argument or environment."""
    if explicit_key:
        return explicit_key
    return os.getenv("KRATOS_API_KEY", "")


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
    """Returns the configured local Kratos gateway base URL."""
    return (os.getenv("KRATOS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def get_endpoint_url() -> str:
    """Returns the local Kratos gateway chat-completions URL."""
    direct_url = os.getenv("KRATOS_CHAT_ENDPOINT")
    if direct_url:
        return direct_url
    base = get_base_url()
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def get_model_endpoint_url() -> str:
    """Returns the local Kratos gateway model-listing URL."""
    direct_url = os.getenv("KRATOS_MODEL_ENDPOINT")
    if direct_url:
        return direct_url
    base = get_base_url()
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def get_default_model() -> str:
    """Returns the explicitly configured Kratos model ID."""
    return os.getenv("KRATOS_MODEL", "").strip()


def _extract_model_catalog(payload: Any) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Extracts unique model IDs and full model metadata from gateway response schemas."""
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
    model_details: dict[str, dict[str, Any]] = {}
    for item in raw_list:
        mid = ""
        meta: dict[str, Any] = {}
        if isinstance(item, str):
            mid = item.strip()
            meta = {"id": mid}
        elif isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
            meta = dict(item)
            meta["id"] = mid
        if mid and mid not in model_ids:
            model_ids.append(mid)
            model_details[mid] = meta
    return model_ids, model_details


def _extract_model_ids(payload: Any) -> list[str]:
    """Extracts unique model IDs from various LLM gateway response schemas."""
    ids, _ = _extract_model_catalog(payload)
    return ids


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "supported"}:
            return True
        if normalized in {"false", "no", "0", "unsupported"}:
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def _normalize_modality(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"text", "text_input", "text_output", "text_generation"}:
        return "text"
    if normalized in {"image", "images", "image_input", "image_url", "vision", "visual"}:
        return "image"
    if normalized in {"audio", "audio_input", "audio_output", "speech"}:
        return "audio"
    if normalized in {"video", "video_input", "video_output"}:
        return "video"
    return None


def _collect_modalities(value: Any) -> list[str]:
    """Normalize common gateway modality fields while preserving their order."""
    if isinstance(value, dict):
        # Modality descriptors can be directional, e.g. text+image -> text.
        result: list[str] = []
        for key in ("input", "inputs", "input_modalities", "output", "outputs", "output_modalities"):
            if key in value:
                for modality in _collect_modalities(value[key]):
                    if modality not in result:
                        result.append(modality)
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            for modality in _collect_modalities(item):
                if modality not in result:
                    result.append(modality)
        return result
    if not isinstance(value, str):
        return []

    result = []
    # Accept compact declarations such as "text+image" and "text, image".
    for token in value.replace("->", "+").replace(",", "+").split("+"):
        modality = _normalize_modality(token.strip())
        if modality and modality not in result:
            result.append(modality)
    return result


def _model_modalities(model: dict[str, Any]) -> dict[str, Any]:
    """Build explicit, user-facing input/output modality flags for a model."""
    sources = [model]
    for key in ("architecture", "model_info", "capabilities"):
        nested = model.get(key)
        if isinstance(nested, dict):
            sources.append(nested)

    input_modalities: list[str] = []
    output_modalities: list[str] = []
    input_known = False
    input_modalities_complete = False
    output_known = False

    for source in sources:
        for key in ("input_modalities", "input_modalities_supported", "input"):
            if key in source:
                input_known = True
                input_modalities_complete = True
                for modality in _collect_modalities(source[key]):
                    if modality not in input_modalities:
                        input_modalities.append(modality)
        for key in ("output_modalities", "output_modalities_supported", "output"):
            if key in source:
                output_known = True
                for modality in _collect_modalities(source[key]):
                    if modality not in output_modalities:
                        output_modalities.append(modality)

        modalities = source.get("modalities")
        if isinstance(modalities, dict):
            if any(key in modalities for key in ("input", "inputs", "input_modalities")):
                input_known = True
                input_modalities_complete = True
                for modality in _collect_modalities({key: modalities[key] for key in ("input", "inputs", "input_modalities") if key in modalities}):
                    if modality not in input_modalities:
                        input_modalities.append(modality)
            if any(key in modalities for key in ("output", "outputs", "output_modalities")):
                output_known = True
                for modality in _collect_modalities({key: modalities[key] for key in ("output", "outputs", "output_modalities") if key in modalities}):
                    if modality not in output_modalities:
                        output_modalities.append(modality)
        elif modalities is not None:
            input_known = True
            input_modalities_complete = True
            for modality in _collect_modalities(modalities):
                if modality not in input_modalities:
                    input_modalities.append(modality)

        capabilities = source.get("capabilities")
        if isinstance(capabilities, (str, list, tuple, set)):
            capability_modalities = _collect_modalities(capabilities)
            if capability_modalities:
                input_known = True
                for modality in capability_modalities:
                    if modality not in input_modalities:
                        input_modalities.append(modality)

        declaration = source.get("modality")
        if isinstance(declaration, str):
            if "->" in declaration:
                left, right = declaration.split("->", 1)
                input_known = output_known = True
                input_modalities_complete = True
                for modality in _collect_modalities(left):
                    if modality not in input_modalities:
                        input_modalities.append(modality)
                for modality in _collect_modalities(right):
                    if modality not in output_modalities:
                        output_modalities.append(modality)
            else:
                input_known = True
                input_modalities_complete = True
                for modality in _collect_modalities(declaration):
                    if modality not in input_modalities:
                        input_modalities.append(modality)

    image_flag: bool | None = None
    text_flag: bool | None = None
    for source in sources:
        for key in ("supports_image_input", "supports_image", "supports_images", "image_input", "vision", "supports_vision"):
            if key in source and (value := _as_bool(source[key])) is not None:
                image_flag = value
                input_known = True
                break
        if image_flag is True:
            if "image" not in input_modalities:
                input_modalities.append("image")
            input_known = True
        for key in ("supports_text_input", "supports_text", "text_input"):
            if key in source and (value := _as_bool(source[key])) is not None:
                text_flag = value
                input_known = True
                break
        if text_flag is True:
            if "text" not in input_modalities:
                input_modalities.append("text")
            input_known = True

    if image_flag is None and "image" in input_modalities:
        image_flag = True
    elif image_flag is None and input_modalities_complete:
        image_flag = False
    if text_flag is None and "text" in input_modalities:
        text_flag = True
    elif text_flag is None and input_modalities_complete:
        text_flag = False

    if not input_known:
        label = "Unknown"
    elif image_flag and text_flag:
        label = "Text + image"
    elif text_flag and image_flag is False:
        label = "Text only"
    elif text_flag:
        label = "Text input; image support unknown"
    elif image_flag and text_flag is False:
        label = "Image only"
    elif image_flag:
        label = "Image input; text support unknown"
    elif input_modalities:
        label = " + ".join(modality.title() for modality in input_modalities) + " input"
    else:
        label = "No recognized input modalities"

    return {
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "supports_text_input": text_flag,
        "supports_image_input": image_flag,
        "modality_label": label,
    }


def get_model_catalog(
    endpoint: str | None = None,
    timeout: float = 3.0,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Fetch gateway models with normalized input/output modality flags.

    The catalog is informational. Runtime requests still use only KRATOS_MODEL.
    A missing modality declaration is reported as ``Unknown`` instead of being
    inferred from a model ID.
    """
    global _cached_model_details, _cached_models, _cache_timestamp

    target_endpoint = endpoint or get_model_endpoint_url()
    now = time.time()
    if (
        not refresh
        and endpoint is None
        and _cache_timestamp
        and (now - _cache_timestamp) < _CACHE_TTL_SECONDS
    ):
        details = _cached_model_details
    else:
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.get(target_endpoint, headers=authenticate(), timeout=timeout)
            if response.status_code == 200:
                model_ids, fetched_details = _extract_model_catalog(response.json())
                _cached_model_details = fetched_details
                configured = get_default_model()
                _cached_models = [configured] if configured and configured in model_ids else []
                _cache_timestamp = now
                details = fetched_details
            else:
                details = _cached_model_details if endpoint is None else {}
        except Exception as exc:
            logger.debug("Could not fetch Kratos model catalog: %s", exc)
            details = _cached_model_details if endpoint is None else {}

    catalog = []
    for model_id, metadata in details.items():
        catalog.append({"id": model_id, **_model_modalities(metadata)})
    return catalog


def get_model(
    endpoint: str | None = None,
    timeout: float = 3.0,
    refresh: bool = False,
) -> list[str]:
    """Return only the configured Kratos model when the gateway advertises it."""
    global _cached_models, _cache_timestamp, _cached_model_details

    target_endpoint = endpoint or get_model_endpoint_url()
    now = time.time()
    configured_model = get_default_model()
    if not configured_model:
        return []

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
            model_list, model_details = _extract_model_catalog(result_json)
            if model_list:
                _cache_timestamp = now
                _cached_model_details = model_details
                _cached_models = [configured_model] if configured_model in model_list else []
                return list(_cached_models)
    except Exception as exc:
        logger.debug("Operation error suppressed: %s", exc)

    # If fetch failed, fall back to cached models if available
    return [configured_model] if configured_model else []


def fetch_models(endpoint: str | None = None, timeout: float = 3.0, refresh: bool = False) -> list[str]:
    """Alias for get_model."""
    return get_model(endpoint=endpoint, timeout=timeout, refresh=refresh)


def get_available_models(refresh: bool = False, timeout: float = 3.0) -> list[str]:
    """Return the configured runtime model; use get_model_catalog for catalog details."""
    return get_model(refresh=refresh, timeout=timeout)


def get_normal_mode_model() -> str:
    """Normal chat uses the same single Kratos reasoning model as agent mode."""
    return get_default_model()


def get_request_timeout() -> float:
    """Returns the request timeout in seconds."""
    raw = os.getenv("KRATOS_TIMEOUT")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_TIMEOUT_SECONDS


def get_max_retries() -> int:
    """Returns the maximum retry attempts for transient errors."""
    raw = os.getenv("KRATOS_MAX_RETRIES")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_MAX_RETRIES


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


