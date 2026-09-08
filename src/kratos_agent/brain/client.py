from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
import uuid
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
        tools: Optional[List[Dict[str, Any]]] = None,
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
                msg_dict: Dict[str, Any] = {"role": "assistant"}
                raw_tools = msg.get("tool_calls") or msg.get("metadata", {}).get("tool_calls")
                if content is not None:
                    c_str = str(content)
                    if raw_tools and (c_str.startswith("call:") or not c_str.strip()):
                        msg_dict["content"] = None
                    else:
                        msg_dict["content"] = c_str
                else:
                    msg_dict["content"] = None

                if raw_tools:
                    clean_tcs = []
                    for tc in raw_tools:
                        if "type" in tc and "function" in tc:
                            clean_tcs.append(tc)
                        else:
                            tc_id = tc.get("call_id") or tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                            tc_name = tc.get("name", "tool")
                            tc_args = tc.get("arguments", {})
                            if isinstance(tc_args, dict):
                                tc_args = json.dumps(tc_args)
                            clean_tcs.append({
                                "id": tc_id,
                                "type": "function",
                                "function": {
                                    "name": tc_name,
                                    "arguments": tc_args,
                                }
                            })
                    msg_dict["tool_calls"] = clean_tcs
                formatted_messages.append(msg_dict)
            elif role == "tool":
                tool_call_id = msg.get("tool_call_id") or msg.get("metadata", {}).get("call_id") or f"call_{uuid.uuid4().hex[:8]}"
                tool_name = msg.get("name") or msg.get("metadata", {}).get("name") or "tool"
                formatted_messages.append({
                    "role": "tool",
                    "content": str(content),
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                })
            else:
                if isinstance(content, list):
                    text_parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                    formatted_messages.append({"role": "user", "content": "\n".join(text_parts)})
                else:
                    formatted_messages.append({"role": "user", "content": str(content)})

        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": formatted_messages,
            "stream": stream,
        }

        if tools:
            clean_tools = []
            for t in tools:
                if "type" in t and "function" in t:
                    clean_tools.append({
                        "type": t["type"],
                        "function": {
                            "name": t["function"].get("name"),
                            "description": t["function"].get("description", ""),
                            "parameters": t["function"].get("parameters", {}),
                        }
                    })
                elif "name" in t:
                    clean_tools.append({
                        "type": "function",
                        "function": {
                            "name": t.get("name"),
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {}),
                        }
                    })
            if clean_tools:
                payload["tools"] = clean_tools
                payload["tool_choice"] = "auto"

        return payload

    def complete(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[float] = None,
        task_id: str = "",
        stream: bool = True,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Executes generation with streaming, latency tracking, and native OpenAI tool call parsing.
        Returns: (text, tool_calls)
        where tool_calls is a list of dicts: [{'id': ..., 'name': ..., 'args': {...}}]
        """
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
        raw_tool_calls: Dict[int, Dict[str, Any]] = {}
        parsed_tool_calls: List[Dict[str, Any]] = []
        ttft_recorded = False

        try:
            if stream:
                payload = self.build_envelope(target_model, messages, system_instruction, stream=True, tools=tools)
                headers = authenticate()

                attempt = 0
                last_error: Optional[Exception] = None
                while attempt <= retries:
                    attempt += 1
                    try:
                        with self.session.post(
                            self.endpoint_url,
                            headers=headers,
                            json=payload,
                            stream=True,
                            timeout=req_timeout,
                        ) as resp:
                            if resp.status_code == 200:
                                has_events = False
                                for line in resp.iter_lines(decode_unicode=False):
                                    if not line:
                                        continue
                                    line_str = line.decode('utf-8', errors='replace').strip() if isinstance(line, (bytes, bytearray)) else str(line).strip()
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
                                                    has_events = True
                                                    if not ttft_recorded:
                                                        metrics.ttft_ms = (time.monotonic() - start_time) * 1000
                                                        ttft_recorded = True
                                                    chunks.append(content)
                                                    if on_chunk:
                                                        try:
                                                            on_chunk(content)
                                                        except Exception:
                                                            pass
                                                tc_list = delta.get("tool_calls")
                                                if tc_list:
                                                    has_events = True
                                                    if not ttft_recorded:
                                                        metrics.ttft_ms = (time.monotonic() - start_time) * 1000
                                                        ttft_recorded = True
                                                    for tc in tc_list:
                                                        idx = tc.get("index", 0)
                                                        if idx not in raw_tool_calls:
                                                            raw_tool_calls[idx] = {
                                                                "id": tc.get("id", ""),
                                                                "name": "",
                                                                "arguments": "",
                                                            }
                                                        if tc.get("id"):
                                                            raw_tool_calls[idx]["id"] = tc.get("id")
                                                        fn = tc.get("function", {})
                                                        if fn.get("name"):
                                                            raw_tool_calls[idx]["name"] = fn.get("name")
                                                        if fn.get("arguments"):
                                                            raw_tool_calls[idx]["arguments"] += fn.get("arguments")
                                        except Exception:
                                            continue

                                if not has_events:
                                    try:
                                        json_resp = resp.json()
                                        choices = json_resp.get("choices", [])
                                        if choices:
                                            msg = choices[0].get("message", {})
                                            if msg.get("content"):
                                                chunks.append(msg["content"])
                                            for tc in msg.get("tool_calls", []):
                                                fn = tc.get("function", {})
                                                raw_args = fn.get("arguments", "{}")
                                                try:
                                                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                                                except Exception:
                                                    parsed_args = {"raw": raw_args}
                                                parsed_tool_calls.append({
                                                    "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                                    "name": fn.get("name", "tool"),
                                                    "args": parsed_args,
                                                })
                                    except Exception:
                                        pass
                                break
                            self._handle_http_error_status(resp, target_model, attempt, retries)
                    except (BrainBadRequestError, BrainNotFoundError):
                        raise
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, BrainRateLimitError, BrainServerError) as exc:
                        last_error = exc
                        if attempt <= retries:
                            time.sleep(0.5 * (2 ** (attempt - 1)))
                            continue
                        break
                    except Exception as exc:
                        last_error = exc
                        break
                if last_error and not chunks and not raw_tool_calls and not parsed_tool_calls:
                    if isinstance(last_error, requests.exceptions.ConnectionError):
                        raise BrainConnectionError(
                            f"Brain LLM is not running on {self.endpoint_url} (connection refused). "
                            f"Please ensure Brain gateway is running."
                        ) from last_error
                    elif isinstance(last_error, requests.exceptions.Timeout):
                        raise BrainTimeoutError(
                            f"Brain request timed out after {req_timeout}s at {self.endpoint_url}."
                        ) from last_error
                    elif isinstance(last_error, BrainError):
                        raise last_error
                    elif last_error:
                        raise BrainError(f"Brain request failed: {last_error}") from last_error
            else:
                text_out, non_stream_tools = self.request_non_streaming_full(target_model, messages, system_instruction, retries, req_timeout, tools=tools)
                if text_out:
                    chunks.append(text_out)
                parsed_tool_calls.extend(non_stream_tools)
                if on_chunk and text_out:
                    try:
                        on_chunk(text_out)
                    except Exception:
                        pass

            for idx in sorted(raw_tool_calls.keys()):
                item = raw_tool_calls[idx]
                name = item["name"]
                call_id = item["id"] or f"call_{uuid.uuid4().hex[:8]}"
                raw_args = item["arguments"]
                try:
                    parsed_args = json.loads(raw_args) if raw_args else {}
                except Exception:
                    parsed_args = {"raw": raw_args}
                parsed_tool_calls.append({"id": call_id, "name": name, "args": parsed_args})

            text = "".join(chunks).strip()
            total_duration = (time.monotonic() - start_time) * 1000
            metrics.generation_ms = max(0.0, total_duration - metrics.context_build_ms)
            metrics.total_ms = total_duration
            metrics.output_tokens = max(1, len(text) // 4)
            metrics.status = "completed"
            latency_tracker.record_completed(metrics)

            if text or parsed_tool_calls:
                return text, parsed_tool_calls

            raise BrainError(f"Model {target_model} returned an empty response.")
        except Exception as exc:
            metrics.status = "failed"
            metrics.error = str(exc)
            metrics.total_ms = (time.monotonic() - start_time) * 1000
            latency_tracker.record_completed(metrics)
            raise

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_retries: Optional[int] = None,
        timeout: Optional[float] = None,
        task_id: str = "",
        stream: bool = True,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        text, tool_calls = self.complete(
            model=model,
            messages=messages,
            system_instruction=system_instruction,
            tools=tools,
            max_retries=max_retries,
            timeout=timeout,
            task_id=task_id,
            stream=stream,
            on_chunk=on_chunk,
        )
        if not text and tool_calls:
            call_strs = [f"call:{c['name']}{json.dumps(c['args'])}" for c in tool_calls]
            return "\n".join(call_strs)
        return text

    def request_non_streaming_full(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: int = 2,
        timeout: float = 60.0,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        target_model = model or get_default_model()
        payload = self.build_envelope(target_model, messages, system_instruction, stream=False, tools=tools)
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
                        content = (msg.get("content") or "").strip()
                        tool_calls: List[Dict[str, Any]] = []
                        for tc in msg.get("tool_calls", []):
                            fn = tc.get("function", {})
                            raw_args = fn.get("arguments", "{}")
                            try:
                                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                            except Exception:
                                parsed_args = {"raw": raw_args}
                            tool_calls.append({
                                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                "name": fn.get("name", "tool"),
                                "args": parsed_args,
                            })
                        return content, tool_calls
                    return "", []

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

    def request_non_streaming(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> str:
        text, _ = self.request_non_streaming_full(model, messages, system_instruction, max_retries, timeout)
        return text

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
                        for line in resp.iter_lines(decode_unicode=False):
                            if not line:
                                continue
                            line_str = line.decode('utf-8', errors='replace').strip()
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
