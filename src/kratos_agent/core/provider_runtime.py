"""Provider adapter protocol and Brain implementation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
import json

from .runtime_contracts import ModelCapabilities, ModelResponse, ToolCall


class ModelAdapter(ABC):
    """Abstract base class defining the provider model contract."""
    capabilities: ModelCapabilities

    @abstractmethod
    def complete(self, request: Dict[str, Any], on_chunk: Optional[Callable[[str], None]] = None) -> ModelResponse: ...


ModelProvider = ModelAdapter


class BrainAdapter(ModelAdapter):
    """A normalized OpenAI-compatible adapter over the Brain gateway client."""
    def __init__(self, model: str, client: Any) -> None:
        self.model = model
        self.client = client
        self.capabilities = ModelCapabilities(streaming=True, tool_calling=True, reasoning=True)

    def complete(self, request: Dict[str, Any], on_chunk: Optional[Callable[[str], None]] = None) -> ModelResponse:
        from kratos_agent.brain.chat_model import extract_tool_calls_from_text
        
        messages = []
        for message in request.get("messages", []):
            role = message.get("role", "user")
            if role == "system":
                continue
            if role == "assistant":
                content = message.get("content")
                tool_calls_meta = message.get("tool_calls") or message.get("metadata", {}).get("tool_calls")
                msg_dict: Dict[str, Any] = {"role": "assistant"}
                if content is not None:
                    c_str = str(content).strip()
                    if tool_calls_meta and (c_str.startswith("call:") or not c_str):
                        msg_dict["content"] = None
                    elif c_str:
                        msg_dict["content"] = c_str
                    else:
                        msg_dict["content"] = None
                else:
                    msg_dict["content"] = None
                if tool_calls_meta:
                    msg_dict["tool_calls"] = tool_calls_meta
                messages.append(msg_dict)
            elif role == "tool":
                tool_name = str(message.get("name") or message.get("metadata", {}).get("name") or "tool")
                call_id = str(message.get("tool_call_id") or message.get("metadata", {}).get("call_id") or "")
                messages.append({
                    "role": "tool",
                    "content": str(message.get("content", "")),
                    "tool_call_id": call_id,
                    "name": tool_name,
                })
            else:
                messages.append({"role": "user", "content": message.get("content", "")})

        system_content = request.get("system", "")
        tools = request.get("tools", [])
        if tools:
            tool_hint = (
                "\n\n## AVAILABLE TOOLS\n"
                "You have access to the following tools defined by JSON schemas:\n"
                + json.dumps(tools, ensure_ascii=False, indent=2)
                + "\n\n## TOOL CALLING INSTRUCTIONS:\n"
                "- Whenever you need to perform an action (read a file, write a file, edit code, run terminal commands, etc.), you MUST invoke the tool.\n"
                "- Invoke a tool ONLY using the format: call:TOOL_NAME{\"param\": \"value\"}\n"
                "- Examples:\n"
                "  call:write_file{\"file_path\": \"app.py\", \"content\": \"print('hello')\"}\n"
                "  call:read_file{\"file_path\": \"package.json\"}\n"
                "  call:run_terminal_command{\"command\": \"npm test\"}\n"
                "- Do NOT write explanations or conversational text instead of calling a tool when action is required.\n"
                "- Output the tool call directly.\n"
            )
            system_content = (system_content or "") + tool_hint

        # Intelligent tool-call detection for streaming:
        # Buffer early tokens to detect if output starts with a tool call (call:, <tool_call>, {"name":)
        buffered_chunks: List[str] = []
        is_tool_stream = False
        streaming_active = False
        recent_text = ""

        def _stream_filter(chunk: str) -> None:
            nonlocal is_tool_stream, streaming_active, recent_text
            if not on_chunk or is_tool_stream:
                return

            recent_text += chunk
            if "call:" in recent_text or "<tool_call>" in recent_text or '{"name":' in recent_text:
                is_tool_stream = True
                buffered_chunks.clear()
                return

            if not streaming_active:
                buffered_chunks.append(chunk)
                buf_str = "".join(buffered_chunks)
                stripped = buf_str.lstrip()

                # Check if this looks like a tool call starting
                if any(stripped.startswith(p) for p in ("call:", "<tool_call", "{\"name\"", "{\n  \"name\"")):
                    is_tool_stream = True
                    buffered_chunks.clear()
                    return

                # If buffer has enough characters or newline and not matching tool call start, flush it
                has_enough = len(stripped) >= 12 or "\n" in stripped
                might_be_tool = any(p.startswith(stripped[:min(len(stripped), 5)]) for p in ("call:", "<tool_call>"))
                if has_enough or not might_be_tool:
                    streaming_active = True
                    for c in buffered_chunks:
                        on_chunk(c)
                    buffered_chunks.clear()
            else:
                on_chunk(chunk)

        import uuid
        raw_text = ""
        native_tool_calls: List[Dict[str, Any]] = []

        handled = False
        if hasattr(self.client, "complete") and callable(getattr(self.client, "complete")):
            try:
                raw_result = self.client.complete(
                    model=self.model,
                    messages=messages,
                    system_instruction=system_content,
                    tools=tools,
                    stream=True,
                    on_chunk=_stream_filter if on_chunk else None,
                )
                if isinstance(raw_result, tuple) and len(raw_result) == 2:
                    raw_text, native_tool_calls = raw_result
                    handled = True
                elif isinstance(raw_result, str):
                    raw_text = raw_result
                    handled = True
            except Exception:
                handled = False

        if not handled and hasattr(self.client, "generate") and callable(getattr(self.client, "generate")):
            raw_text = self.client.generate(
                model=self.model,
                messages=messages,
                system_instruction=system_content,
                on_chunk=_stream_filter if on_chunk else None,
            )

        if on_chunk and not is_tool_stream and buffered_chunks:
            for c in buffered_chunks:
                on_chunk(c)
            buffered_chunks.clear()

        text, text_tool_calls = extract_tool_calls_from_text(raw_text)

        all_calls: List[ToolCall] = []
        seen_calls = set()

        for ntc in native_tool_calls:
            cid = ntc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            name = ntc.get("name", "tool")
            args = ntc.get("args") or {}
            key = (name, json.dumps(args, sort_keys=True))
            seen_calls.add(key)
            all_calls.append(ToolCall(name=name, arguments=args, call_id=cid))

        for ttc in text_tool_calls:
            name = ttc.get("name", "tool")
            args = ttc.get("args") or {}
            key = (name, json.dumps(args, sort_keys=True))
            if key not in seen_calls:
                cid = ttc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                seen_calls.add(key)
                all_calls.append(ToolCall(name=name, arguments=args, call_id=cid))

        return ModelResponse(
            text=text,
            tool_calls=all_calls,
            finish_reason="tool_calls" if all_calls else "stop",
            raw=raw_text,
        )


BrainProvider = BrainAdapter
OmnirouteAdapter = BrainAdapter
OmniRouteProvider = BrainAdapter
