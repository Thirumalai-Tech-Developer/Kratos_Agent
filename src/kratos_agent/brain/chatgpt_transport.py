"""Stateless, streaming Responses transport for authorized ChatGPT plan use."""

from __future__ import annotations

import json

import requests

from .chatgpt_auth import RESOURCE, chatgpt_accounts
from .config import (
    BrainBadRequestError,
    BrainConnectionError,
    BrainError,
    BrainRateLimitError,
    BrainTimeoutError,
)


def responses_request(payload: dict) -> dict:
    instructions, inputs = [], []
    for message in payload.get("messages", []):
        role, content = message.get("role", "user"), message.get("content")
        if role in {"system", "developer"}:
            instructions.append(str(content or ""))
            continue
        if role == "tool":
            inputs.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": str(content or ""),
                }
            )
            continue
        if role == "assistant":
            if content:
                inputs.append({"role": "assistant", "content": str(content)})
            for call in message.get("tool_calls", []):
                # Opaque provider state preserves reasoning continuity without
                # asking for, exposing or inventing hidden reasoning text.
                inputs.extend(call.get("provider_items", []))
                function = call["function"]
                inputs.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": function["name"],
                        "namespace": "kratos",
                        "arguments": function["arguments"],
                    }
                )
            continue
        if isinstance(content, list):
            parts = []
            for part in content:
                kind = part.get("type") if isinstance(part, dict) else "text"
                if kind in {"text", "input_text"}:
                    parts.append(
                        {
                            "type": "input_text",
                            "text": part.get("text", "")
                            if isinstance(part, dict)
                            else str(part),
                        }
                    )
                elif kind == "image_url":
                    image = part["image_url"]
                    parts.append(
                        {
                            "type": "input_image",
                            "image_url": image.get("url")
                            if isinstance(image, dict)
                            else image,
                            "detail": image.get("detail", "auto")
                            if isinstance(image, dict)
                            else "auto",
                        }
                    )
                elif kind == "input_image" or kind == "input_file":
                    parts.append(part)
                else:
                    raise BrainBadRequestError(
                        f"ChatGPT plan usage does not support input type '{kind}'"
                    )
            content = parts
        inputs.append({"role": "user", "content": content or ""})
    request = {
        "model": payload["model"],
        "input": inputs,
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
    }
    if instructions:
        request["instructions"] = "\n\n".join(instructions)
    functions = [
        {"type": "function", **tool["function"], "strict": False}
        for tool in payload.get("tools", [])
    ]
    if functions:
        request["tools"] = [
            {
                "type": "namespace",
                "name": "kratos",
                "description": "Kratos tools executed by the local runtime",
                "tools": functions,
            }
        ]
    if payload.get("reasoning_effort"):
        request["reasoning"] = {"effort": payload["reasoning_effort"]}
    return request


def completed_response(body: dict):
    from kratos_agent.sdk.client import KratosCompletion, KratosToolCall

    text, calls = [], []
    output = body.get("output", [])
    reasoning = [
        {
            key: item[key]
            for key in ("type", "id", "summary", "encrypted_content")
            if key in item
        }
        for item in output
        if item.get("type") == "reasoning" and item.get("encrypted_content")
    ]
    for item in output:
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    text.append(part.get("refusal", ""))
        elif item.get("type") == "function_call":
            try:
                arguments = json.loads(item.get("arguments", "{}"))
            except (ValueError, TypeError) as exc:
                raise BrainError(
                    "ChatGPT returned malformed function arguments"
                ) from exc
            if (
                not isinstance(arguments, dict)
                or not item.get("call_id")
                or not item.get("name")
            ):
                raise BrainError("ChatGPT returned an invalid function call")
            if item.get("namespace") not in {None, "kratos"}:
                raise BrainError("ChatGPT returned an unexpected tool namespace")
            calls.append(
                KratosToolCall(
                    item["call_id"],
                    item["name"],
                    arguments,
                    reasoning if not calls else [],
                )
            )
    usage = body.get("usage") or {}
    return KratosCompletion(
        "".join(text).strip(),
        calls,
        "tool_calls" if calls else "stop",
        {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        },
    )


def stream_events(response):
    """Read SSE data records, including multi-line data and a final partial record."""
    lines = []
    for raw in response.iter_lines(decode_unicode=False):
        line = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if not line:
            if lines:
                yield json.loads("\n".join(lines))
                lines = []
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip())
    if lines:
        yield json.loads("\n".join(lines))


def completion_events(client, payload, timeout):
    from kratos_agent.core.run_scope import current_runtime
    from kratos_agent.sdk.client import _check_cancelled, _close_stream_on_cancel

    runtime = current_runtime.get()
    token = chatgpt_accounts.access_token(client.chatgpt_account_id)
    request = responses_request(payload)
    if runtime is not None:
        # Count the actual transformed payload, including opaque continuation state.
        count = runtime.context.count_request(
            {
                "messages": request["input"],
                "tools": request.get("tools", []),
                "system": request.get("instructions", ""),
            }
        )
        if (
            count
            > runtime.context.budget.max_input_tokens
            - runtime.context.budget.reserve_output_tokens
        ):
            raise BrainBadRequestError(
                "ChatGPT request exceeds the current context budget"
            )
    try:
        _check_cancelled()
        with client._post(
            RESOURCE + "/responses",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
            json=request,
            stream=True,
            timeout=timeout,
        ) as response:
            if response.status_code == 429:
                raise BrainRateLimitError(
                    "ChatGPT account usage limit reached; check ChatGPT Settings > Usage"
                )
            if response.status_code != 200:
                raise BrainError(
                    f"ChatGPT inference failed (HTTP {response.status_code}); verify the account permission and selected model"
                )
            with _close_stream_on_cancel(response):
                yield from _response_events(response, runtime)
                return
    except requests.Timeout as exc:
        _check_cancelled()
        raise BrainTimeoutError("ChatGPT model request timed out") from exc
    except requests.ConnectionError as exc:
        _check_cancelled()
        raise BrainConnectionError(
            "The ChatGPT inference endpoint is unreachable"
        ) from exc
    except (requests.RequestException, ValueError, UnicodeDecodeError) as exc:
        _check_cancelled()
        raise BrainError("ChatGPT returned an interrupted or invalid stream") from exc


def _response_events(response, runtime):
    from kratos_agent.sdk.client import _check_cancelled

    for event in stream_events(response):
        _check_cancelled()
        if runtime is not None and runtime._cancellation_flag.is_set():
            raise InterruptedError("ChatGPT model stream cancelled")
        kind = event.get("type")
        if kind == "response.output_text.delta":
            yield str(event.get("delta", ""))
        elif kind == "response.completed":
            body = event.get("response") or {}
            if body.get("status") != "completed":
                raise BrainError("ChatGPT did not complete inference")
            result = completed_response(body)
            if not result.text and not result.tool_calls:
                raise BrainError("ChatGPT completed with an empty response")
            yield result
            return
        elif kind in {"response.failed", "response.incomplete", "error"}:
            error = (
                event.get("error")
                or (event.get("response") or {}).get("error")
                or event
            )
            code = str(error.get("code", "unknown_error"))
            if code in {
                "subscription_sharing_usage_limit_exceeded",
                "subscription_sharing_usage_unavailable",
            }:
                raise BrainRateLimitError(
                    "ChatGPT plan usage is unavailable or its limit was reached; check ChatGPT Settings > Usage"
                )
            raise BrainError(
                f"ChatGPT inference ended with {kind}; no completed result was recorded"
            )
    raise BrainError("ChatGPT stream ended without response.completed")


def complete_chatgpt(client, payload, timeout, on_chunk):
    from kratos_agent.sdk.client import KratosCompletion

    for item in completion_events(client, payload, timeout):
        if isinstance(item, KratosCompletion):
            return item
        if on_chunk and item:
            client._notify_chunk(on_chunk, item)
    raise BrainError("ChatGPT did not return a completed result")
