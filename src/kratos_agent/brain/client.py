"""Compatibility facade over the first-party Kratos model SDK."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

from kratos_agent.brain.config import (
    get_default_model,
    get_endpoint_url,
    get_max_retries,
    get_model_request_options,
    get_request_timeout,
)
from kratos_agent.core.latency_tracker import latency_tracker
from kratos_agent.sdk import KratosClient

logger = logging.getLogger(__name__)


class BrainClient:
    """Legacy application-facing API backed only by KratosClient."""

    def __init__(self, endpoint_url: str | None = None):
        self.endpoint_url = endpoint_url or get_endpoint_url()
        self.sdk = KratosClient(self.endpoint_url)

    @property
    def session(self):
        """Compatibility access for existing diagnostics and tests."""
        return self.sdk.session

    def build_envelope(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a Kratos SDK request using the local gateway's chat contract."""
        request = self.sdk.build_request(model, messages, system_instruction, stream=stream, tools=tools)
        request.update(get_model_request_options(model))
        return request

    def complete_with_sdk(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        task_id: str = "",
        stream: bool = True,
        on_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """The previous SDK entry point now delegates to the Kratos-owned SDK."""
        return self.complete(
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

    def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        task_id: str = "",
        stream: bool = True,
        on_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return text and validated native tool calls from the Kratos gateway."""
        target_model = model or get_default_model()
        metrics = latency_tracker.start_request(
            task_id=task_id,
            model=target_model,
            provider="kratos-sdk",
            context_tokens=len(str(system_instruction or "")) // 4
            + sum(len(str(message.get("content", ""))) // 4 for message in messages),
            history_messages=len(messages),
        )
        started = time.monotonic()
        try:
            request = self.build_envelope(target_model, messages, system_instruction, stream=stream, tools=tools)
            response = self.sdk.complete(
                request,
                stream=stream,
                on_chunk=on_chunk,
                max_retries=max_retries if max_retries is not None else get_max_retries(),
                timeout=timeout if timeout is not None else get_request_timeout(),
            )
            calls = [{"id": call.id, "name": call.name, "args": call.arguments} for call in response.tool_calls]
            duration_ms = (time.monotonic() - started) * 1000
            metrics.ttft_ms = metrics.ttft_ms or duration_ms
            metrics.generation_ms = duration_ms
            metrics.total_ms = duration_ms
            metrics.output_tokens = response.usage.get("completion_tokens", max(1, len(response.text) // 4))
            metrics.status = "completed"
            latency_tracker.record_completed(metrics)
            return response.text, calls
        except Exception as exc:
            metrics.status = "failed"
            metrics.error = str(exc)
            metrics.total_ms = (time.monotonic() - started) * 1000
            latency_tracker.record_completed(metrics)
            raise

    def generate(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        task_id: str = "",
        stream: bool = True,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        text, tool_calls = self.complete(
            model, messages, system_instruction, tools, max_retries, timeout, task_id, stream, on_chunk
        )
        if not text and tool_calls:
            return "\n".join(f"call:{call['name']}{json.dumps(call['args'], ensure_ascii=False)}" for call in tool_calls)
        return text

    def request_non_streaming_full(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        return self.complete(model, messages, system_instruction, tools, max_retries, timeout, stream=False)

    def request_non_streaming(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> str:
        text, _ = self.request_non_streaming_full(model, messages, system_instruction, max_retries, timeout)
        return text

    def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> Iterator[str]:
        request = self.build_envelope(model or get_default_model(), messages, system_instruction, stream=True)
        yield from self.sdk.stream_text(
            request,
            max_retries=max_retries if max_retries is not None else get_max_retries(),
            timeout=timeout if timeout is not None else get_request_timeout(),
        )

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system_instruction: str | None = None,
        timeout: float | None = None,
    ) -> Iterator[dict[str, str]]:
        for chunk in self.stream(model, messages, system_instruction, timeout=timeout):
            yield {"content": chunk}
