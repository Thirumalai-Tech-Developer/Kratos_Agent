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
                content = message.get("content", "")
                if not content and "tool_calls" in message:
                    call_strs = [f"call:{c.get('name')}{json.dumps(c.get('arguments', {}))}" for c in message["tool_calls"]]
                    content = "\n".join(call_strs)
                if not content:
                    content = "Executing requested tool."
                msg_dict: Dict[str, Any] = {"role": "assistant", "content": content}
                messages.append(msg_dict)
            elif role == "tool":
                tool_name = message.get("name") or "tool"
                messages.append({
                    "role": "user",
                    "content": f"[Tool Result for {tool_name}]:\n{message.get('content', '')}"
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

        def _stream_filter(chunk: str) -> None:
            nonlocal is_tool_stream, streaming_active
            if not on_chunk or is_tool_stream:
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
                has_enough = len(stripped) >= 10 or "\n" in stripped
                might_be_tool = any(p.startswith(stripped[:min(len(stripped), 5)]) for p in ("call:", "<tool_call>"))
                if has_enough or not might_be_tool:
                    streaming_active = True
                    for c in buffered_chunks:
                        on_chunk(c)
                    buffered_chunks.clear()
            else:
                if "call:" in chunk or "<tool_call>" in chunk:
                    is_tool_stream = True
                    return
                on_chunk(chunk)

        raw = self.client.generate(
            model=self.model,
            messages=messages,
            system_instruction=system_content,
            on_chunk=_stream_filter if on_chunk else None,
        )

        if on_chunk and not is_tool_stream and buffered_chunks:
            for c in buffered_chunks:
                on_chunk(c)
            buffered_chunks.clear()
        text, parsed = extract_tool_calls_from_text(raw)
        calls = [
            ToolCall(
                name=item["name"],
                arguments=item.get("args", {}),
                call_id=item.get("id") or "",
            )
            for item in parsed
        ]
        return ModelResponse(
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            raw=raw,
        )


BrainProvider = BrainAdapter
OmnirouteAdapter = BrainAdapter
OmniRouteProvider = BrainAdapter
