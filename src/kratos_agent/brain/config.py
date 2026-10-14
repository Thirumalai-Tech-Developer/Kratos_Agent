from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
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
_catalog_last_attempt: float = 0.0
_catalog_endpoint: str = ""
_catalog_cache_key: str = ""
_catalog_lock = threading.RLock()

PUBLIC_MODELS: list[str] = []


class ModelCatalogUnavailable(RuntimeError):
    """The gateway could not confirm the models available for explicit selection."""


def get_api_key(explicit_key: str | None = None) -> str:
    """Returns configured API key from argument or environment."""
    if explicit_key:
        return explicit_key
    return os.getenv("KRATOS_API_KEY", "")


def get_model_provider() -> str:
    from .account_store import account_store
    provider = (os.getenv("KRATOS_MODEL_PROVIDER") or account_store.read().get("provider", "gateway")).lower().strip()
    if provider not in {"gateway", "chatgpt", "chatgpt-web", "browser-web"}:
        raise ValueError("KRATOS_MODEL_PROVIDER must be gateway, chatgpt, chatgpt-web or browser-web")
    return provider


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
    if get_model_provider() == "chatgpt":
        return "https://api.openai.com/v1"
    if get_model_provider() in {"chatgpt-web", "browser-web"}:
        return "https://chatgpt.com"
    return (os.getenv("KRATOS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def get_endpoint_url() -> str:
    """Returns the local Kratos gateway chat-completions URL."""
    if get_model_provider() == "chatgpt":
        return "https://api.openai.com/v1/responses"
    if get_model_provider() in {"chatgpt-web", "browser-web"}:
        return "https://chatgpt.com"
    direct_url = os.getenv("KRATOS_CHAT_ENDPOINT")
    if direct_url:
        return direct_url
    base = get_base_url()
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def get_model_endpoint_url() -> str:
    """Returns the local Kratos gateway model-listing URL."""
    if get_model_provider() == "chatgpt":
        return "https://api.openai.com/v1/models"
    if get_model_provider() in {"chatgpt-web", "browser-web"}:
        return "https://chatgpt.com/backend-api/models"
    direct_url = os.getenv("KRATOS_MODEL_ENDPOINT")
    if direct_url:
        return direct_url
    base = get_base_url()
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def get_default_model() -> str:
    """Returns the explicitly configured Kratos model ID."""
    if os.getenv("KRATOS_RUNTIME_MODEL"):
        return os.environ["KRATOS_RUNTIME_MODEL"].strip()
    if get_model_provider() in {"chatgpt", "chatgpt-web", "browser-web"}:
        from .account_store import account_store
        return account_store.selected_model(get_model_provider())
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


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _model_limits(model: dict[str, Any]) -> dict[str, Any]:
    sources = [model]
    for key in ("model_info", "limits", "capabilities"):
        nested = model.get(key)
        if isinstance(nested, dict):
            sources.append(nested)

    limits: dict[str, Any] = {
        "context_length": None,
        "max_input_tokens": None,
        "max_output_tokens": None,
        "effort_tiers": [],
        "selected_effort": None,
    }
    for key in ("context_length", "max_input_tokens", "max_output_tokens"):
        for source in sources:
            value = _positive_int(source.get(key))
            if value:
                limits[key] = value
                break

    for source in sources:
        tiers = source.get("effort_tiers")
        if isinstance(tiers, (list, tuple)):
            normalized = [str(tier).strip() for tier in tiers if str(tier).strip()]
            if normalized:
                limits["effort_tiers"] = normalized
                limits["selected_effort"] = normalized[-1]
                break
    return limits


def _modality_badges(model_info: dict[str, Any]) -> list[str]:
    badges = []
    text_support = model_info.get("supports_text_input")
    if text_support is True or (model_info.get("is_configured") and text_support is None):
        badges.append("Text 📝")
    if model_info.get("supports_image_input") is True:
        badges.append("Vision 👁️")
    return badges


def get_model_catalog(
    endpoint: str | None = None,
    timeout: float = 3.0,
    refresh: bool = False,
    strict: bool = False,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Read saved gateway models; only explicit refresh replaces a known catalog.

    Runtime requests use only the explicitly selected KRATOS_MODEL.
    A missing modality declaration is reported as ``Unknown`` instead of being
    inferred from a model ID. If the endpoint is unavailable, the configured
    model is still returned with its text-chat baseline and unknown limits.
    """
    global _cached_model_details, _cached_models, _cache_timestamp, _catalog_last_attempt, _catalog_endpoint, _catalog_cache_key

    if endpoint is None and get_model_provider() in {"chatgpt-web", "browser-web"}:
        from .chatgpt_web import chatgpt_web_accounts
        configured = get_default_model()
        try:
            models = chatgpt_web_accounts.models(timeout=timeout, refresh=refresh)
        except BrainError as exc:
            if strict:
                raise ModelCatalogUnavailable(str(exc)) from exc
            logger.debug("Browser model catalog unavailable: %s", exc)
            return []
        return [{**item, "is_configured": item["id"] == configured, "metadata_available": True, "provider": item["id"].split("/")[0]}
                for item in models]

    if endpoint is None and get_model_provider() == "chatgpt":
        from .chatgpt_auth import chatgpt_accounts
        configured = get_default_model()
        return [{"id": item["id"], "display_name": item.get("display_name", item["id"]),
                 **_model_modalities(item), **_model_limits(item), "metadata_available": True,
                 "is_configured": item["id"] == configured, "provider": "chatgpt", "access_verified": False}
                for item in chatgpt_accounts.models(timeout=timeout)]

    target_endpoint = endpoint or get_model_endpoint_url()
    cache_path = _gateway_catalog_cache_path(cache_path)
    target_key = _gateway_catalog_cache_key(target_endpoint)
    fetched = False
    with _catalog_lock:
        if not refresh and _cache_timestamp and _catalog_cache_key == target_key:
            details = _cached_model_details
        else:
            saved = None if refresh else _read_gateway_catalog_cache(cache_path, target_endpoint)
            if saved is not None:
                _restore_gateway_catalog_cache(saved, target_endpoint)
                details = _cached_model_details
            else:
                _catalog_last_attempt = time.time()
                session = requests.Session()
                session.trust_env = False
                try:
                    response = session.get(target_endpoint, headers=authenticate(), timeout=timeout)
                    if response.status_code == 200:
                        model_ids, fetched_details = _extract_model_catalog(response.json())
                        _cached_model_details = fetched_details
                        configured = get_default_model()
                        _cached_models = [configured] if configured and configured in model_ids else []
                        _cache_timestamp = time.time()
                        _catalog_endpoint = target_endpoint
                        _catalog_cache_key = target_key
                        details = fetched_details
                        fetched = True
                    else:
                        if strict:
                            raise ModelCatalogUnavailable("The gateway model catalog is unavailable. Check provider connections and try again.")
                        details = _cached_model_details if _catalog_cache_key == target_key else {}
                except ModelCatalogUnavailable:
                    raise
                except requests.Timeout as exc:
                    if strict:
                        raise ModelCatalogUnavailable("The gateway model catalog timed out. Try refetching the model list.") from exc
                    details = _cached_model_details if _catalog_cache_key == target_key else {}
                except Exception as exc:
                    if strict:
                        raise ModelCatalogUnavailable("Cannot read the gateway model catalog. Check that OmniRoute is running.") from exc
                    logger.debug("Could not fetch Kratos model catalog: %s", exc)
                    details = _cached_model_details if _catalog_cache_key == target_key else {}
                finally:
                    session.close()
        catalog = _normalized_gateway_catalog(details, strict=strict)
        if fetched or (not refresh and _cache_timestamp and _catalog_cache_key == target_key
                       and _read_gateway_catalog_cache(cache_path, target_endpoint) is None):
            _save_gateway_catalog_cache(cache_path, target_endpoint, catalog)
        return catalog


def _normalized_gateway_catalog(details: dict[str, dict[str, Any]], *, strict: bool) -> list[dict[str, Any]]:
    catalog = []
    configured_model = get_default_model()
    for model_id, metadata in details.items():
        # Saved rows are already normalized. Preserve Unknown modality flags;
        # an empty normalized modality list is not a new provider declaration.
        modalities = (
            {key: metadata.get(key) for key in (
                "input_modalities", "output_modalities", "supports_text_input",
                "supports_image_input", "modality_label")}
            if metadata.get("metadata_available") is True and "modality_label" in metadata
            else _model_modalities(metadata)
        )
        entry = {
            "id": model_id,
            "name": metadata.get("name") or metadata.get("display_name") or model_id,
            "provider": metadata.get("provider") or metadata.get("owned_by") or model_id.partition("/")[0],
            **({"available": metadata["available"]} if type(metadata.get("available")) is bool else {}),
            **({"disabled_reason": metadata["disabled_reason"]} if isinstance(metadata.get("disabled_reason"), str) else {}),
            "supported_parameters": metadata.get('supported_parameters', []),
            "supports_temperature": metadata.get('supports_temperature'),
            **modalities,
            **_model_limits(metadata),
            "metadata_available": True,
            "is_configured": model_id == configured_model,
        }
        entry["modality_badges"] = _modality_badges(entry)
        catalog.append(entry)

    if configured_model and not any(item["id"] == configured_model for item in catalog):
        fallback = {
            "id": configured_model,
            "name": configured_model,
            "provider": configured_model.partition("/")[0],
            **({"available": False, "disabled_reason": "The gateway has not advertised this model."} if strict else {}),
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "supports_text_input": True,
            "supports_image_input": None,
            "modality_label": "Text input; vision support unknown",
            "context_length": None,
            "max_input_tokens": None,
            "max_output_tokens": None,
            "effort_tiers": [],
            "selected_effort": None,
            "metadata_available": False,
            "is_configured": True,
        }
        fallback["modality_badges"] = _modality_badges(fallback)
        catalog.insert(0, fallback)
    return catalog


def _gateway_catalog_cache_key(endpoint: str) -> str:
    return hashlib.sha256((endpoint + '\0' + json.dumps(authenticate(), sort_keys=True)).encode()).hexdigest()


def _gateway_catalog_cache_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    override = os.getenv("KRATOS_CATALOG_CACHE_PATH")
    return Path(override) if override else Path.cwd() / ".kratos" / "gateway-model-catalog.json"


def _restore_gateway_catalog_cache(rows: list[dict[str, Any]], endpoint: str) -> None:
    global _cached_model_details, _cached_models, _cache_timestamp, _catalog_endpoint, _catalog_cache_key
    _cached_model_details = {row["id"]: dict(row) for row in rows}
    configured = get_default_model()
    _cached_models = [configured] if configured in _cached_model_details else []
    _cache_timestamp = time.time()
    _catalog_endpoint = endpoint
    _catalog_cache_key = _gateway_catalog_cache_key(endpoint)


def _read_gateway_catalog_cache(path: Path | None, endpoint: str) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or saved.get("key") != _gateway_catalog_cache_key(endpoint):
            return None
        rows = saved.get("models")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("id"), str)
            or not row["id"] or row.get("metadata_available") is not True for row in rows
        ):
            return None
        return rows
    except (OSError, ValueError, TypeError):
        return None


def _save_gateway_catalog_cache(path: Path | None, endpoint: str, rows: list[dict[str, Any]]) -> None:
    if path is None:
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        saved = {'version': 1, 'key': _gateway_catalog_cache_key(endpoint), 'saved_at': time.time(),
                 'models': [row for row in rows if row.get('metadata_available')]}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(saved, handle, ensure_ascii=False)
        temporary.replace(path)
    except (OSError, ValueError, TypeError):
        logger.debug('Gateway catalog cache could not be saved')
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.debug('Gateway catalog cache temporary file could not be removed')


def get_runtime_model_catalog(
    timeout: float = 3.0, refresh: bool = False, strict: bool = False, cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Show gateway models together with saved extension connections.

    Browser metadata is captured at connection time; opening the picker never
    starts a browser request. Expired sessions are reported when used or refreshed
    in the extension, without hiding other providers.
    """
    from .account_store import account_store
    from .web_providers import WEB_PROVIDERS

    state = account_store.read()
    active_provider = get_model_provider()
    configured = get_default_model()
    active_account = os.getenv("KRATOS_RUNTIME_ACCOUNT_ID") or state.get("active_web_account", "")
    # A failed first lookup must not be saved as a successful empty catalog.
    # The outer strict flag controls whether a missing combined catalog raises.
    kwargs = {"timeout": timeout, "refresh": refresh, "strict": True}
    if active_provider != "gateway":
        base = (os.getenv("KRATOS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        kwargs["endpoint"] = os.getenv("KRATOS_MODEL_ENDPOINT") or f"{base}/models"
    gateway_error = None
    target_endpoint = kwargs.get("endpoint") or get_model_endpoint_url()
    cache_path = _gateway_catalog_cache_path(cache_path)
    catalog_cached = False
    with _catalog_lock:
        gateway = None if refresh else _read_gateway_catalog_cache(cache_path, target_endpoint)
        if gateway is not None:
            _restore_gateway_catalog_cache(gateway, target_endpoint)
            catalog_cached = True
        else:
            try:
                gateway = get_model_catalog(**kwargs, cache_path=cache_path)
                _save_gateway_catalog_cache(cache_path, target_endpoint, gateway)
            except ModelCatalogUnavailable as exc:
                gateway = _read_gateway_catalog_cache(cache_path, target_endpoint)
                gateway, gateway_error = gateway if gateway is not None else [], exc
                catalog_cached = bool(gateway)
    catalog = []
    for entry in gateway:
        if not entry.get("metadata_available"):
            continue
        cached = {"catalog_cached": True} if catalog_cached else {}
        if gateway_error:
            cached["catalog_notice"] = str(gateway_error)
        catalog.append({**entry, **cached, "connection_provider": "gateway", "connection_label": "OmniRoute",
                        "selection_key": "gateway:" + entry["id"],
                        "is_configured": active_provider == "gateway" and entry["id"] == configured})
    for account_id, record in state.get("web_accounts", {}).items():
        provider_id = record.get("provider_id", "chatgpt-web")
        if not record.get("storage_state") or provider_id not in WEB_PROVIDERS:
            continue
        route = "chatgpt-web" if provider_id == "chatgpt-web" else "browser-web"
        label = WEB_PROVIDERS[provider_id]["name"] + " · browser"
        for model in record.get("models", []):
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            entry = {**model, **_model_modalities({"supports_text_input": True, **model}), **_model_limits(model),
                     "name": model.get("display_name") or model["id"],
                     "provider": provider_id, "provider_name": label, "metadata_available": True,
                     "connection_provider": route, "connection_account_id": account_id,
                     "connection_label": label, "catalog_cached": True,
                     "selection_key": route + ":" + account_id + ":" + model["id"],
                     "is_configured": active_provider == route and account_id == active_account
                                      and model["id"] == configured}
            if gateway_error:
                entry["catalog_notice"] = str(gateway_error)
            catalog.append(entry)
    if strict and gateway_error and not catalog:
        raise gateway_error
    return catalog


def get_model_request_options(model_id: str | None = None) -> dict[str, Any]:
    """Return cached gateway generation settings without making a network call."""
    if get_model_provider() in {"chatgpt", "chatgpt-web", "browser-web"}:
        return {}
    target_model = model_id or get_default_model()
    if _catalog_cache_key != _gateway_catalog_cache_key(get_model_endpoint_url()):
        return {}
    metadata = _cached_model_details.get(target_model)
    if not metadata:
        return {}
    limits = _model_limits(metadata)
    options = {}
    if limits["max_output_tokens"]:
        options["max_tokens"] = limits["max_output_tokens"]
    if limits["selected_effort"]:
        options["reasoning_effort"] = limits["selected_effort"]
    return options


def get_model(
    endpoint: str | None = None,
    timeout: float = 3.0,
    refresh: bool = False,
) -> list[str]:
    """Return the configured model from the saved catalog."""
    configured = get_default_model()
    if not configured:
        return []
    rows = get_model_catalog(endpoint=endpoint, timeout=timeout, refresh=refresh)
    return [configured] if any(row["id"] == configured for row in rows) else []


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
    if not raw and get_model_provider() in {"chatgpt-web", "browser-web"}:
        return 240.0
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


class BrainToolCallError(BrainError):
    """A rejected tool response may be corrected by the model before execution."""


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

# Compatibility constant only. Importing configuration must never start a
# browser operation or require an authenticated account; catalog reads are lazy.
