"""Normalize Kratos SDK completions into the agent-loop response contract.

The adapter is deliberately thin: request construction, retries, authentication,
and transport errors belong to KratosClient. This layer normalizes responses
into Kratos' ModelResponse contract without hiding real failures.
"""
from __future__ import annotations

import json
import inspect
import re
import uuid
from collections.abc import Callable
from typing import Any

from kratos_agent.brain.config import BrainToolCallError

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
        if not isinstance(calls, list):
            raise BrainToolCallError("The provider returned an invalid tool-call collection.")
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not call["name"].strip():
                raise BrainToolCallError("The provider returned a tool call without a valid name.")
            name = call["name"].strip()
            args = call.get("args", call.get("arguments", {}))
            if not isinstance(args, dict):
                raise BrainToolCallError("The provider returned tool arguments that are not a JSON object.")
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

        pending_text = ""
        suppress_text = False

        def stream_filter(chunk: str) -> None:
            nonlocal pending_text, suppress_text
            if not on_chunk or suppress_text:
                return
            pending_text += chunk
            prefixes = ('call:', '<tool', '<||DSML||', '<|DSML|', '<|toolcallbegin|>', '{"name"')
            visible = []
            while pending_text:
                candidate = re.sub(r'\s+', '', pending_text).replace('｜', '|')
                if any(candidate.lower().startswith(prefix.lower()) for prefix in prefixes):
                    suppress_text = True
                    pending_text = ''
                    break
                if candidate and any(prefix.lower().startswith(candidate.lower()) for prefix in prefixes):
                    break
                visible.append(pending_text[0])
                pending_text = pending_text[1:]
            if visible:
                on_chunk(''.join(visible))

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

        if on_chunk and not suppress_text and pending_text:
            on_chunk(pending_text)

        text, text_calls = extract_tool_calls_from_text(str(raw_text or ""), strict=True)
        if not isinstance(native_calls, list):
            raise BrainToolCallError("The provider returned an invalid tool-call collection.")
        all_calls = self._dedupe_calls([*native_calls, *text_calls])
        advertised = {str((tool.get("function") or tool).get("name", "")) for tool in tools if isinstance(tool, dict)}
        if any(call.name not in advertised for call in all_calls):
            raise BrainToolCallError("The provider requested a tool that was not supplied in this request.")

        return ModelResponse(
            text=text,
            tool_calls=all_calls,
            finish_reason="tool_calls" if all_calls else "stop",
            raw=str(raw_text or ""),
        )
