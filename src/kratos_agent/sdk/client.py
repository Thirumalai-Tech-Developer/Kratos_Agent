"""Kratos model SDK for the local `/v1/chat/completions` gateway.

This is Kratos-owned code. It implements the gateway contract directly and has
no Anthropic, OpenAI, Kimi, or other model-provider SDK dependency.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import requests

from kratos_agent.brain.config import (
    BrainBadRequestError,
    BrainConnectionError,
    BrainError,
    BrainNotFoundError,
    BrainRateLimitError,
    BrainServerError,
    BrainTimeoutError,
    get_api_key,
    get_endpoint_url,
    get_max_retries,
    get_request_timeout,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KratosToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class KratosCompletion:
    text: str = ""
    tool_calls: list[KratosToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)


class KratosClient:
    """Small typed client for Kratos's single configured reasoning gateway."""

    def __init__(
        self,
        endpoint_url: str | None = None,
        *,
        api_key: str | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.endpoint_url = (endpoint_url or get_endpoint_url()).strip()
        self.api_key = api_key if api_key is not None else get_api_key()
        self.max_retries = max(0, get_max_retries() if max_retries is None else int(max_retries))
        self.timeout = timeout if timeout is not None else get_request_timeout()
        self.session = requests.Session()
        self.session.trust_env = False
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def complete(
        self,
        payload: dict[str, Any],
        *,
        stream: bool | None = None,
        on_chunk: Callable[[str], None] | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> KratosCompletion:
        """Complete one request, returning validated text and native tool calls."""
        request_payload = dict(payload)
        self._require_configured_model(request_payload.get("model"))
        should_stream = bool(request_payload.get("stream", True) if stream is None else stream)
        request_payload["stream"] = should_stream
        retries = self.max_retries if max_retries is None else max(0, int(max_retries))
        req_timeout = self.timeout if timeout is None else timeout

        if should_stream:
            result = self._stream_completion(request_payload, req_timeout, retries, on_chunk)
            if result.text or result.tool_calls:
                return result
            # Some compatible gateways return an empty SSE stream. Retry once as
            # JSON; this is a transport recovery on the same Kratos endpoint.
            fallback_payload = dict(request_payload)
            fallback_payload["stream"] = False
            result = self._json_completion(fallback_payload, req_timeout, 0)
            if on_chunk and result.text:
                self._notify_chunk(on_chunk, result.text)
        else:
            result = self._json_completion(request_payload, req_timeout, retries)
            if on_chunk and result.text:
                self._notify_chunk(on_chunk, result.text)

        if not result.text and not result.tool_calls:
            raise BrainError(f"Kratos model returned an empty response for '{request_payload.get('model', 'unknown')}'.")
        return result

    def build_request(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        *,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Normalize agent messages and tool schemas for Kratos's gateway."""
        from kratos_agent.brain.config import get_default_model

        normalized: list[dict[str, Any]] = []
        if system_instruction:
            normalized.append({"role": "system", "content": system_instruction})
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content", "")
            if role in ("system", "developer"):
                normalized.append({"role": "system", "content": str(content)})
            elif role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": None if content is None else str(content)}
                raw_calls = message.get("tool_calls") or (message.get("metadata") or {}).get("tool_calls")
                if raw_calls:
                    calls = []
                    for call in raw_calls:
                        if "type" in call and "function" in call:
                            calls.append(call)
                            continue
                        arguments = call.get("arguments", call.get("args", {}))
                        calls.append({
                            "id": call.get("call_id") or call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": {
                                "name": call.get("name", "tool"),
                                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
                            },
                        })
                    item["tool_calls"] = calls
                normalized.append(item)
            elif role == "tool":
                metadata = message.get("metadata") or {}
                normalized.append({
                    "role": "tool",
                    "content": str(content),
                    "tool_call_id": message.get("tool_call_id") or metadata.get("call_id") or f"call_{uuid.uuid4().hex[:12]}",
                    "name": message.get("name") or metadata.get("name") or "tool",
                })
            elif isinstance(content, list) and not any(
                isinstance(part, dict) and part.get("type") in ("image_url", "image", "input_audio")
                for part in content
            ):
                normalized.append({
                    "role": "user",
                    "content": "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content),
                })
            else:
                normalized.append({"role": role if role == "user" else "user", "content": content if isinstance(content, list) else str(content)})

        target_model = model or get_default_model()
        self._require_configured_model(target_model)
        request: dict[str, Any] = {"model": target_model, "messages": normalized, "stream": stream}
        if tools:
            normalized_tools = []
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
                name = function.get("name")
                if not name:
                    continue
                normalized_tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": function.get("description", ""),
                        "parameters": function.get("parameters", {}),
                    },
                })
            if normalized_tools:
                request["tools"] = normalized_tools
                request["tool_choice"] = "auto"
        return request

    def stream_text(
        self,
        payload: dict[str, Any],
        *,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """Yield text deltas from one Kratos response."""
        request_payload = dict(payload)
        self._require_configured_model(request_payload.get("model"))
        request_payload["stream"] = True
        retries = self.max_retries if max_retries is None else max(0, int(max_retries))
        req_timeout = self.timeout if timeout is None else timeout
        chunks: list[str] = []
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with self.session.post(
                    self.endpoint_url,
                    headers=self._headers(),
                    json=request_payload,
                    stream=True,
                    timeout=req_timeout,
                ) as response:
                    if response.status_code != 200:
                        self._raise_response_error(response, str(request_payload.get("model", "unknown")))
                    for raw_line in response.iter_lines(decode_unicode=False):
                        if not raw_line:
                            continue
                        line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
                        if not line.startswith("data:"):
                            continue
                        data_text = line[5:].strip()
                        if data_text == "[DONE]":
                            break
                        try:
                            event = json.loads(data_text)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices or not isinstance(choices[0], dict):
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            chunks.append(content)
                            yield content
                if not chunks:
                    fallback = dict(request_payload)
                    fallback["stream"] = False
                    result = self._json_completion(fallback, req_timeout, 0)
                    if result.text:
                        yield result.text
                return
            except (BrainRateLimitError, BrainServerError) as exc:
                last_error = exc
            except (BrainBadRequestError, BrainNotFoundError, BrainError):
                raise
            except requests.exceptions.Timeout:
                last_error = BrainTimeoutError(f"Kratos model request timed out after {req_timeout}s.")
            except requests.exceptions.ConnectionError:
                last_error = BrainConnectionError(f"Kratos model gateway is unreachable at {self.endpoint_url}.")
            except requests.exceptions.RequestException as exc:
                last_error = BrainError(f"Kratos model transport failed: {type(exc).__name__}.")
            if attempt < retries and not chunks:
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
            else:
                if last_error:
                    raise last_error

    def _stream_completion(
        self,
        payload: dict[str, Any],
        timeout: float,
        retries: int,
        on_chunk: Callable[[str], None] | None,
    ) -> KratosCompletion:
        chunks: list[str] = []
        tool_deltas: dict[int, dict[str, str]] = {}
        usage: dict[str, int] = {}
        finish_reason = "stop"

        def consume(response: requests.Response) -> None:
            nonlocal finish_reason, usage
            for raw_line in response.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
                if not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if data_text == "[DONE]":
                    break
                try:
                    event = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(event.get("usage"), dict):
                    usage = _integer_usage(event["usage"])
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] if isinstance(choices[0], dict) else {}
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    chunks.append(content)
                    if on_chunk:
                        self._notify_chunk(on_chunk, content)
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
                for item in delta.get("tool_calls") or []:
                    if not isinstance(item, dict):
                        continue
                    index = int(item.get("index", 0) or 0)
                    state = tool_deltas.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    state["id"] = str(item.get("id") or state["id"])
                    function = item.get("function") or {}
                    state["name"] += str(function.get("name") or "")
                    state["arguments"] += str(function.get("arguments") or "")

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with self.session.post(
                    self.endpoint_url,
                    headers=self._headers(),
                    json=payload,
                    stream=True,
                    timeout=timeout,
                ) as response:
                    if response.status_code != 200:
                        self._raise_response_error(response, str(payload.get("model", "unknown")))
                    consume(response)
                break
            except (BrainRateLimitError, BrainServerError) as exc:
                last_error = exc
            except (BrainBadRequestError, BrainNotFoundError, BrainError):
                raise
            except requests.exceptions.Timeout as exc:
                last_error = BrainTimeoutError(f"Kratos model request timed out after {timeout}s.")
            except requests.exceptions.ConnectionError as exc:
                last_error = BrainConnectionError(f"Kratos model gateway is unreachable at {self.endpoint_url}.")
            except requests.exceptions.RequestException as exc:
                last_error = BrainError(f"Kratos model transport failed: {type(exc).__name__}.")
            if attempt < retries and not chunks and not tool_deltas:
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
                continue
            if last_error:
                raise last_error

        calls = _finish_tool_calls(tool_deltas)
        if not chunks and not calls:
            return KratosCompletion(usage=usage, finish_reason=finish_reason)
        return KratosCompletion("".join(chunks).strip(), calls, finish_reason, usage)

    def _json_completion(self, payload: dict[str, Any], timeout: float, retries: int) -> KratosCompletion:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = self.session.post(
                    self.endpoint_url,
                    headers=self._headers(),
                    json=payload,
                    timeout=timeout,
                )
                if response.status_code != 200:
                    self._raise_response_error(response, str(payload.get("model", "unknown")))
                body = response.json()
                if not isinstance(body, dict):
                    raise BrainError("Kratos gateway returned an invalid response object.")
                choices = body.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    return KratosCompletion(usage=_integer_usage(body.get("usage", {})))
                choice = choices[0]
                message = choice.get("message") or {}
                if not isinstance(message, dict):
                    raise BrainError("Kratos gateway returned an invalid message object.")
                text = message.get("content")
                if text is None:
                    text = ""
                if not isinstance(text, str):
                    raise BrainError("Kratos gateway returned non-text message content.")
                calls = _parse_tool_calls(message.get("tool_calls") or [])
                return KratosCompletion(
                    text=text.strip(),
                    tool_calls=calls,
                    finish_reason=str(choice.get("finish_reason") or "stop"),
                    usage=_integer_usage(body.get("usage", {})),
                )
            except (BrainRateLimitError, BrainServerError) as exc:
                last_error = exc
            except (BrainBadRequestError, BrainNotFoundError, BrainError):
                raise
            except requests.exceptions.Timeout as exc:
                last_error = BrainTimeoutError(f"Kratos model request timed out after {timeout}s.")
            except requests.exceptions.ConnectionError as exc:
                last_error = BrainConnectionError(f"Kratos model gateway is unreachable at {self.endpoint_url}.")
            except requests.exceptions.RequestException as exc:
                last_error = BrainError(f"Kratos model transport failed: {type(exc).__name__}.")
            except (ValueError, json.JSONDecodeError) as exc:
                raise BrainError(f"Kratos gateway returned invalid JSON ({type(exc).__name__}).") from exc
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
        if last_error:
            raise last_error
        raise BrainError("Kratos gateway request failed without a response.")

    def list_models(self, endpoint_url: str | None = None) -> list[str]:
        """Return model IDs exposed by the same local gateway."""
        url = endpoint_url or _models_endpoint(self.endpoint_url)
        try:
            response = self.session.get(url, headers=self._headers(), timeout=min(self.timeout, 10.0))
            if response.status_code != 200:
                self._raise_response_error(response, "model catalog")
            body = response.json()
        except requests.exceptions.Timeout as exc:
            raise BrainTimeoutError("Kratos model catalog request timed out.") from exc
        except requests.exceptions.ConnectionError as exc:
            raise BrainConnectionError(f"Kratos model gateway is unreachable at {url}.") from exc
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise BrainError(f"Kratos model catalog request failed: {type(exc).__name__}.") from exc
        entries = body if isinstance(body, list) else body.get("data", body.get("models", body.get("items", []))) if isinstance(body, dict) else []
        ids: list[str] = []
        for item in entries if isinstance(entries, list) else []:
            if isinstance(item, str):
                model_id = item.strip()
            elif isinstance(item, dict):
                model_id = str(item.get("id") or item.get("name") or "").strip()
            else:
                model_id = ""
            if model_id and model_id not in ids:
                ids.append(model_id)
        return ids

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Connection": "Keep-Alive"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _require_configured_model(model: Any) -> str:
        """Reject unconfigured IDs and attempts to route around the one Kratos model."""
        from kratos_agent.brain.config import get_default_model

        configured = get_default_model()
        if not configured:
            raise BrainError(
                "No Kratos model is configured. Set KRATOS_MODEL to the exact model ID "
                "served by the local Kratos gateway; no provider or model fallback is enabled."
            )
        requested = str(model or "").strip()
        if requested != configured:
            raise BrainError(
                f"Kratos is locked to KRATOS_MODEL='{configured}'. Refusing model '{requested or '<empty>'}'."
            )
        return configured

    @staticmethod
    def _notify_chunk(callback: Callable[[str], None], text: str) -> None:
        try:
            callback(text)
        except Exception as exc:
            logger.debug("Kratos stream callback failed: %s", exc)

    @staticmethod
    def _raise_response_error(response: requests.Response, model: str) -> None:
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            detail = error.get("message") if isinstance(error, dict) else None
            detail = str(detail or response.text[:300] or "gateway returned an error")
        except Exception:
            detail = str(response.text[:300] or "gateway returned an error")
        status = response.status_code
        lower = detail.lower()
        if status == 400:
            raise BrainBadRequestError(f"Invalid Kratos model request: {detail}")
        if status == 404:
            raise BrainNotFoundError(f"Kratos endpoint or model '{model}' was not found: {detail}")
        if status in (401, 403):
            raise BrainError(f"Kratos gateway access error (HTTP {status}): {detail}")
        if status == 429:
            raise BrainRateLimitError(f"Kratos gateway rate limit reached (HTTP 429): {detail}")
        if status >= 500:
            if any(term in lower for term in ("invalid token", "authorization failed", "unauthorized", "invalid api key", "authentication failed")):
                raise BrainError("Kratos gateway reported an upstream authentication failure; no provider fallback is configured.")
            raise BrainServerError(f"Kratos gateway server error (HTTP {status}): {detail}")
        raise BrainError(f"Kratos gateway request failed (HTTP {status}): {detail}")


def _integer_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
        item = value.get(key)
        if isinstance(item, (int, float)):
            result[key] = max(0, int(item))
    return result


def _parse_tool_calls(items: Any) -> list[KratosToolCall]:
    if not isinstance(items, list):
        return []
    calls: list[KratosToolCall] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        function = item.get("function") or {}
        if not isinstance(function, dict):
            raise BrainError("Kratos gateway returned an invalid structured tool call.")
        raw_args = function.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError as exc:
                raise BrainError("Kratos gateway returned malformed JSON tool arguments.") from exc
        else:
            arguments = raw_args
        if not isinstance(arguments, dict):
            raise BrainError("Kratos tool arguments must be a JSON object.")
        name = str(function.get("name") or "").strip()
        if not name:
            raise BrainError("Kratos gateway returned a tool call without a name.")
        calls.append(KratosToolCall(str(item.get("id") or f"call_{uuid.uuid4().hex[:12]}"), name, arguments))
    return calls


def _finish_tool_calls(items: dict[int, dict[str, str]]) -> list[KratosToolCall]:
    calls: list[KratosToolCall] = []
    for _, item in sorted(items.items()):
        try:
            arguments = json.loads(item["arguments"] or "{}")
        except json.JSONDecodeError as exc:
            raise BrainError("Kratos gateway streamed malformed JSON tool arguments.") from exc
        if not isinstance(arguments, dict):
            raise BrainError("Kratos streamed tool arguments must be a JSON object.")
        name = item["name"].strip()
        if not name:
            raise BrainError("Kratos gateway streamed a tool call without a name.")
        calls.append(KratosToolCall(item["id"] or f"call_{uuid.uuid4().hex[:12]}", name, arguments))
    return calls


def _models_endpoint(endpoint: str) -> str:
    suffix = "/chat/completions"
    if endpoint.rstrip("/").endswith(suffix):
        return endpoint.rstrip("/")[:-len(suffix)] + "/models"
    if endpoint.rstrip("/").endswith("/models"):
        return endpoint.rstrip("/")
    return endpoint.rstrip("/") + "/models"
