from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterator, List, Optional
import requests

from kratos_agent.brain.config import (
    authenticate,
    get_endpoint_url,
    get_default_model,
    get_request_timeout,
    get_max_retries,
    BrainError,
    BrainConnectionError,
    BrainTimeoutError,
    BrainRateLimitError,
    BrainBadRequestError,
    BrainNotFoundError,
    BrainServerError,
)
from kratos_agent.core.latency_tracker import latency_tracker


class BrainClient:
    """High-speed Brain / OpenAI-compatible API client.
    
    Communicates directly with the Brain gateway ignoring system proxy variables.
    """
    def __init__(self, endpoint_url: Optional[str] = None):
        self.endpoint_url = endpoint_url or get_endpoint_url()
        self._session: Optional[requests.Session] = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            # CRITICAL: Disable system proxy inheritance (HTTP_PROXY, HTTPS_PROXY, ALL_PROXY)
            self._session.trust_env = False
            adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        return self._session

    def build_envelope(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        stream: bool = True,
    ) -> Dict[str, Any]:
        """Builds standard OpenAI-compatible chat payload."""
        target_model = model or get_default_model()
        formatted_messages: List[Dict[str, Any]] = []

        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("system", "developer"):
                formatted_messages.append({"role": "system", "content": str(content)})
            elif role == "assistant":
                msg_dict: Dict[str, Any] = {"role": "assistant", "content": str(content)}
                if "tool_calls" in msg:
                    msg_dict["tool_calls"] = msg["tool_calls"]
                formatted_messages.append(msg_dict)
            elif role == "tool":
                tool_call_id = msg.get("tool_call_id")
                if tool_call_id:
                    formatted_messages.append({
                        "role": "tool",
                        "content": str(content),
                        "tool_call_id": tool_call_id,
                    })
                else:
                    tool_name = msg.get("name", "tool")
                    formatted_messages.append({
                        "role": "user",
                        "content": f"[Tool Result from {tool_name}]:\n{content}",
                    })
            else:
                if isinstance(content, list):
                    text_parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                    formatted_messages.append({"role": "user", "content": "\n".join(text_parts)})
                else:
                    formatted_messages.append({"role": "user", "content": str(content)})

        return {
            "model": target_model,
            "messages": formatted_messages,
            "stream": stream,
        }

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[float] = None,
        task_id: str = "",
        stream: bool = True,
    ) -> str:
        """Executes generation with streaming and latency tracking."""
        start_time = time.monotonic()
        target_model = model or get_default_model()
        retries = max_retries if max_retries is not None else get_max_retries()
        req_timeout = timeout if timeout is not None else get_request_timeout()

        metrics = latency_tracker.start_request(
            task_id=task_id,
            model=target_model,
            provider="brain",
            context_tokens=len(str(system_instruction or "")) // 4 + sum(len(str(m.get("content", ""))) // 4 for m in messages),
            history_messages=len(messages),
        )

        chunks: List[str] = []
        ttft_recorded = False

        try:
            if stream:
                for chunk in self.stream(target_model, messages, system_instruction, retries, req_timeout):
                    if not ttft_recorded and chunk:
                        metrics.ttft_ms = (time.monotonic() - start_time) * 1000
                        ttft_recorded = True
                    chunks.append(chunk)
                text = "".join(chunks).strip()
            else:
                text = self.request_non_streaming(target_model, messages, system_instruction, retries, req_timeout).strip()

            total_duration = (time.monotonic() - start_time) * 1000
            metrics.generation_ms = max(0.0, total_duration - metrics.context_build_ms)
            metrics.total_ms = total_duration
            metrics.output_tokens = max(1, len(text) // 4)
            metrics.status = "completed"
            latency_tracker.record_completed(metrics)

            if text:
                return text
            raise BrainError(f"Model {target_model} returned an empty response.")
        except Exception as exc:
            metrics.status = "failed"
            metrics.error = str(exc)
            metrics.total_ms = (time.monotonic() - start_time) * 1000
            latency_tracker.record_completed(metrics)
            raise

    def request_non_streaming(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> str:
        """Sends a non-streaming request to the Brain endpoint."""
        target_model = model or get_default_model()
        payload = self.build_envelope(target_model, messages, system_instruction, stream=False)
        headers = authenticate()

        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= max_retries:
            attempt += 1
            try:
                resp = self.session.post(
                    self.endpoint_url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        content = msg.get("content", "")
                        return content or ""
                    return ""

                self._handle_http_error_status(resp, target_model, attempt, max_retries)

            except (BrainBadRequestError, BrainNotFoundError):
                raise
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, BrainRateLimitError, BrainServerError) as exc:
                last_error = exc
                if attempt <= max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    continue
                break
            except Exception as exc:
                last_error = exc
                break

        if isinstance(last_error, requests.exceptions.ConnectionError):
            raise BrainConnectionError(
                f"Brain LLM is not running on {self.endpoint_url} (connection refused). "
                f"Please ensure Brain gateway is running."
            ) from last_error
        elif isinstance(last_error, requests.exceptions.Timeout):
            raise BrainTimeoutError(
                f"Brain request timed out after {timeout}s at {self.endpoint_url}."
            ) from last_error
        elif isinstance(last_error, BrainError):
            raise last_error
        elif last_error:
            raise BrainError(f"Brain request failed: {last_error}") from last_error
        raise BrainError(f"Brain gateway unreachable at {self.endpoint_url}.")

    def stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> Iterator[str]:
        """Streams responses from Brain via Server-Sent Events (SSE)."""
        target_model = model or get_default_model()
        payload = self.build_envelope(target_model, messages, system_instruction, stream=True)
        headers = authenticate()

        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= max_retries:
            attempt += 1
            try:
                with self.session.post(
                    self.endpoint_url,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=timeout,
                ) as resp:
                    if resp.status_code == 200:
                        has_chunks = False
                        for line in resp.iter_lines(decode_unicode=True):
                            if not line:
                                continue
                            line_str = line.strip()
                            if line_str.startswith("data:"):
                                chunk_payload = line_str[5:].strip()
                                if chunk_payload == "[DONE]":
                                    break
                                try:
                                    data = json.loads(chunk_payload)
                                    choices = data.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content")
                                        if content:
                                            has_chunks = True
                                            yield content
                                except Exception:
                                    continue

                        # Fallback for server returning non-SSE JSON despite stream=True
                        if not has_chunks:
                            try:
                                json_resp = resp.json()
                                choices = json_resp.get("choices", [])
                                if choices:
                                    msg = choices[0].get("message", {})
                                    content = msg.get("content")
                                    if content:
                                        yield content
                            except Exception:
                                pass
                        return

                    self._handle_http_error_status(resp, target_model, attempt, max_retries)

            except (BrainBadRequestError, BrainNotFoundError):
                raise
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, BrainRateLimitError, BrainServerError) as exc:
                last_error = exc
                if attempt <= max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    continue
                break
            except Exception as exc:
                last_error = exc
                break

        if isinstance(last_error, requests.exceptions.ConnectionError):
            raise BrainConnectionError(
                f"Brain LLM is not running on {self.endpoint_url} (connection refused). "
                f"Please ensure Brain gateway is running."
            ) from last_error
        elif isinstance(last_error, requests.exceptions.Timeout):
            raise BrainTimeoutError(
                f"Brain request timed out after {timeout}s at {self.endpoint_url}."
            ) from last_error
        elif isinstance(last_error, BrainError):
            raise last_error
        elif last_error:
            raise BrainError(f"Brain stream failed: {last_error}") from last_error
        raise BrainError(f"Brain gateway unreachable at {self.endpoint_url}.")

    def _handle_http_error_status(self, resp: requests.Response, model: str, attempt: int, max_retries: int) -> None:
        """Translates HTTP error codes into clean, descriptive Brain exceptions."""
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message") or resp.text[:300]
        except Exception:
            detail = resp.text[:300] if resp.text else ""

        if resp.status_code == 400:
            raise BrainBadRequestError(f"Invalid model request to Brain: {detail}")
        elif resp.status_code == 404:
            raise BrainNotFoundError(f"Brain endpoint or model '{model}' not found: {detail}")
        elif resp.status_code == 429:
            raise BrainRateLimitError(f"Brain rate limit reached (HTTP 429): {detail}")
        elif resp.status_code in (401, 403):
            raise BrainError(f"Brain access error (HTTP {resp.status_code}): {detail}")
        elif resp.status_code >= 500:
            raise BrainServerError(f"Brain server error (HTTP {resp.status_code}): {detail}")
        else:
            raise BrainError(f"Brain returned HTTP {resp.status_code}: {detail}")


# Backward compatibility alias
OmnirouteClient = BrainClient
