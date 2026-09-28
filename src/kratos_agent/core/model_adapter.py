"""Normalize Kratos SDK completions into the agent-loop response contract.

The adapter is deliberately thin: request construction, retries, authentication,
and transport errors belong to KratosClient. This layer normalizes responses
into Kratos' ModelResponse contract without hiding real failures.
"""
from __future__ import annotations

import json
import inspect
import uuid
from collections.abc import Callable
from typing import Any

from .runtime_contracts import ModelCapabilities, ModelResponse, ToolCall


class KratosModelAdapter:
    """Normalize the local Kratos gateway contract into agent-loop responses."""

    def __init__(self, model: str, client: Any) -> None:
        self.model = model
        self.client = client
        self.capabilities = ModelCapabilities(streaming=True, tool_calling=True, reasoning=True)

    @staticmethod
    def _messages(request: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        system_content = str(request.get("system") or "")
        messages: list[dict[str, Any]] = []

        for message in request.get("messages", []):
            role = str(message.get("role", "user"))
            if role == "system":
                content = str(message.get("content") or "").strip()
                if content:
                    system_content = f"{system_content}\n\n{content}" if system_content else content
                continue

            if role == "assistant":
                content = message.get("content")
                tool_calls_meta = message.get("tool_calls") or message.get("metadata", {}).get("tool_calls")
                item: dict[str, Any] = {"role": "assistant", "content": None}
                if content is not None:
                    text = str(content).strip()
                    item["content"] = None if tool_calls_meta and (text.startswith("call:") or not text) else (text or None)
                if tool_calls_meta:
                    item["tool_calls"] = tool_calls_meta
                messages.append(item)
                continue

            if role == "tool":
                messages.append({
                    "role": "tool",
                    "content": str(message.get("content", "")),
                    "tool_call_id": str(message.get("tool_call_id") or message.get("metadata", {}).get("call_id") or ""),
                    "name": str(message.get("name") or message.get("metadata", {}).get("name") or "tool"),
                })
                continue

            messages.append({"role": "user", "content": message.get("content", "")})

        return system_content, messages

    @staticmethod
    def _tool_protocol_hint() -> str:
        """Keep the behavioral tool-call rules compact; schemas are already sent natively."""
        return (
            "\n\nTOOL EXECUTION RULES:\n"
            "- When an action is required, emit a structured tool call immediately; do not narrate first.\n"
            "- Prefer the native tool schema supplied by the API.\n"
            "- If the gateway requires text tool calls, use call:TOOL_NAME{JSON}.\n"
            "- Do not invent tools or output raw DSML control tokens as prose.\n"
            "- After tool results, continue the task until the requested artifact is verified."
        )

    @staticmethod
    def _dedupe_calls(calls: list[dict[str, Any]]) -> list[ToolCall]:
        result: list[ToolCall] = []
        seen: set[tuple[str, str]] = set()
        for call in calls:
            name = str(call.get("name") or "tool")
            args = call.get("args") or call.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if key in seen:
                continue
            seen.add(key)
            result.append(ToolCall(
                name=name,
                arguments=args,
                call_id=str(call.get("id") or call.get("call_id") or f"call_{uuid.uuid4().hex[:8]}"),
            ))
        return result

    def complete(
        self,
        request: dict[str, Any],
        on_chunk: Callable[[str], None] | None = None,
    ) -> ModelResponse:
        from kratos_agent.brain.tool_calls import extract_tool_calls_from_text

        system_content, messages = self._messages(request)
        tools = request.get("tools") or []
        if tools:
            # Do not serialize the full tool schemas into the system prompt again.
            # BrainClient already sends them through the native `tools` field.
            system_content = system_content + self._tool_protocol_hint()

        buffered: list[str] = []
        recent = ""
        suppress_text = False
        streaming_active = False

        def stream_filter(chunk: str) -> None:
            nonlocal recent, suppress_text, streaming_active
            if not on_chunk or suppress_text:
                return
            recent += chunk
            if len(recent) > 256:
                recent = recent[-256:]
            stripped = recent.lstrip()
            tool_prefixes = ("call:", "<tool", "<｜", "<||", '{"name"')
            if any(stripped.startswith(prefix) for prefix in tool_prefixes):
                suppress_text = True
                buffered.clear()
                return
            if not streaming_active:
                buffered.append(chunk)
                candidate = "".join(buffered).lstrip()
                maybe_tool = any(prefix.startswith(candidate[: min(len(candidate), 8)]) for prefix in tool_prefixes)
                if len(candidate) >= 24 or "\n" in candidate or not maybe_tool:
                    streaming_active = True
                    for item in buffered:
                        on_chunk(item)
                    buffered.clear()
            else:
                on_chunk(chunk)

        raw_text = ""
        native_calls: list[dict[str, Any]] = []

        computer_use_tools = any(
            str((tool.get("function") or {}).get("name", "")).startswith(
                ("mcp__computer-use__", "mcp__computer_use__")
            )
            for tool in tools
            if isinstance(tool, dict)
        )
        # `MagicMock` manufactures any requested attribute, so probing it with
        # getattr makes an unconfigured `complete` mock shadow a configured
        # `generate` method. Only prefer SDK methods the client actually defines.
        complete_fn = None
        if computer_use_tools and callable(inspect.getattr_static(self.client, "complete_with_sdk", None)):
            complete_fn = getattr(self.client, "complete_with_sdk")
        if not callable(complete_fn) and callable(inspect.getattr_static(self.client, "complete", None)):
            complete_fn = getattr(self.client, "complete")
        if callable(complete_fn):
            try:
                raw_result = complete_fn(
                    model=self.model,
                    messages=messages,
                    system_instruction=system_content,
                    tools=tools,
                    stream=True,
                    on_chunk=stream_filter if on_chunk else None,
                )
            except TypeError as exc:
                # Only retry for clients that genuinely do not accept on_chunk.
                if "on_chunk" not in str(exc):
                    raise
                raw_result = complete_fn(
                    model=self.model,
                    messages=messages,
                    system_instruction=system_content,
                    tools=tools,
                    stream=True,
                )
            if isinstance(raw_result, tuple) and len(raw_result) == 2:
                raw_text, native_calls = raw_result
            elif isinstance(raw_result, str):
                raw_text = raw_result
            else:
                raise TypeError(
                    f"Unsupported model client response from complete(): {type(raw_result).__name__}"
                )
        else:
            generate_fn = getattr(self.client, "generate", None)
            if not callable(generate_fn):
                raise RuntimeError("Configured model client exposes neither complete() nor generate().")
            # Keep tools here too. Older implementations accidentally dropped them
            # when falling back to generate(), turning an agent request into chat.
            raw_text = generate_fn(
                model=self.model,
                messages=messages,
                system_instruction=system_content,
                tools=tools,
                on_chunk=stream_filter if on_chunk else None,
            )

        if on_chunk and not suppress_text and buffered:
            for item in buffered:
                on_chunk(item)

        text, text_calls = extract_tool_calls_from_text(str(raw_text or ""))
        all_calls = self._dedupe_calls([*native_calls, *text_calls])

        return ModelResponse(
            text=text,
            tool_calls=all_calls,
            finish_reason="tool_calls" if all_calls else "stop",
            raw=str(raw_text or ""),
        )
