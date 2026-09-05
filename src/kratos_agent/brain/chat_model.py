from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from kratos_agent.brain.config import DEFAULT_MODEL, get_default_model
from kratos_agent.brain.client import BrainClient


def _clean_command_payload(cmd_str: str) -> str:
    """Sanitizes terminal command strings by stripping markdown backticks, prefixes, and formatting."""
    cleaned = str(cmd_str).strip()
    backtick_match = re.match(r'^\s*`([^`\n]+)`', cleaned)
    if backtick_match:
        cleaned = backtick_match.group(1).strip()
    else:
        cleaned = re.sub(r'^\s*`+', '', cleaned)
        cleaned = re.sub(r'`+\s*$', '', cleaned)
    cleaned = re.split(r'\n?\s*(?:Tool Inputs:?|```)', cleaned)[0].strip()
    cleaned = re.sub(r'^[a-zA-Z0-9_-]+\s*[:=]\s*\{?', '', cleaned).strip()
    cleaned = re.sub(r'^\{?\s*["\']?(?:command|direct_command|package_name)["\']?\s*[:=]\s*["\']?', '', cleaned).strip()
    cleaned = cleaned.rstrip('"} \t\n').lstrip('"{ \t\n')
    cleaned = re.sub(r'^\s*[`"\']+|[`"\']+\s*$', '', cleaned).strip()
    return cleaned


def clean_file_path(fp_str: str) -> str:
    """Cleans file paths from raw string prefixes and quote artifacts."""
    cleaned = str(fp_str).strip()
    cleaned = re.sub(r'^[rfbRFB]?#*["\']?', '', cleaned)
    cleaned = re.sub(r'["\']?#*$', '', cleaned)
    return cleaned.strip('"\' \t\n')


def _fallback_extract_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Resilient extraction when JSON has unescaped quotes or formatting issues."""
    if "edit_file" in text:
        fp_m = re.search(r'(?<![a-zA-Z0-9_])file_path\s*[:=]\s*["\']?([^"\',\s\n\(\)]+)', text)
        fp = clean_file_path(fp_m.group(1)) if fp_m else "script.py"
        t_m = re.search(r'(?<![a-zA-Z0-9_])target_text\s*[:=]\s*["\'](.*?)["\']\s*,\s*replacement_text', text, re.DOTALL)
        r_m = re.search(r'(?<![a-zA-Z0-9_])replacement_text\s*[:=]\s*["\'](.*?)["\']\s*\}?', text, re.DOTALL)
        if t_m and r_m:
            return {"name": "edit_file", "args": {"file_path": fp, "target_text": t_m.group(1), "replacement_text": r_m.group(1)}}

    if "write_file" in text:
        fp = "script.py"
        fp_m = re.search(r'(?<![a-zA-Z0-9_])file_path\s*[:=]\s*(?:[rfbRFB]#*|#*)?["\']?([^"\',\s\n\(\)]+)', text)
        if fp_m:
            fp = clean_file_path(fp_m.group(1))
            if not fp or fp in ("r#", "r", "#"):
                fp = "script.py"
        start_m = re.search(r'(?<![a-zA-Z0-9_])content\s*[:=]\s*["\']?', text)
        if start_m:
            start_idx = start_m.end()
            end_idx = text.rfind('"')
            if end_idx > start_idx:
                content = text[start_idx:end_idx]
                cleaned = content.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
                return {"name": "write_file", "args": {"file_path": fp, "content": cleaned}}

    if "run_terminal_command" in text:
        cmd_m = re.search(r'(?<![a-zA-Z0-9_])(?:command|direct_command|package_name)\s*[:=]\s*["\']?', text)
        if cmd_m:
            start_idx = cmd_m.end()
            end_idx = text.rfind('"')
            if end_idx > start_idx:
                cmd_val = text[start_idx:end_idx]
                cmd_val = _clean_command_payload(cmd_val)
                return {"name": "run_terminal_command", "args": {"command": cmd_val}}

    return None


def _extract_json_object(text: str, start_idx: int) -> Tuple[Optional[Dict[str, Any]], int, int]:
    """Extracts a JSON object starting from or after start_idx by balancing braces respecting string quotes."""
    idx = text.find("{", start_idx)
    if idx == -1:
        return None, -1, -1

    depth = 0
    in_string = False
    escape = False
    start_pos = idx

    for i in range(idx, len(text)):
        char = text[i]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    raw_json = text[start_pos:i+1]
                    try:
                        parsed = json.loads(raw_json)
                        return parsed, start_pos, i + 1
                    except Exception:
                        try:
                            norm_args = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', raw_json)
                            parsed = json.loads(norm_args)
                            return parsed, start_pos, i + 1
                        except Exception:
                            fallback = _fallback_extract_tool_call(raw_json)
                            if fallback:
                                return fallback.get("args", {}), start_pos, i + 1
                            return None, -1, -1
    return None, -1, -1


def extract_tool_calls_from_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extracts tool calls in formats: Harmony / OpenAI OSS, XML, JSON markdown, and call:name{json}."""
    tool_calls: List[Dict[str, Any]] = []
    removed_spans: List[Tuple[int, int]] = []

    VALID_TOOLS = {
        "write_file", "edit_file", "read_file", "list_directory",
        "grep_search", "run_terminal_command", "fetch_web_page", "search_web",
        "execute_python_code", "run_diagnostics", "open_browser_preview",
        "inspect_page_dom", "interact_with_element", "capture_page_screenshot",
        "save_memory", "read_memory", "clear_memory",
    }

    # 1. Harmony / OpenAI OSS / ChatML channel commentary format:
    # <|channel|>commentary to=call:TOOL_NAME\n<|constrain|>json<|message|>ARGS<|call|>
    harmony_pattern = re.compile(
        r'(?:<\|[^|]*\|>)*\s*(?:to=call:|call:)?([a-zA-Z0-9_]+)[\s\S]*?(?:<\|message\|>|```(?:json)?|\s*)\s*(\{[\s\S]*?\})\s*(?:<\|call\|>|```)?'
    )
    for m in harmony_pattern.finditer(text):
        name = m.group(1)
        if name in VALID_TOOLS:
            try:
                raw_json = m.group(2)
                args = json.loads(raw_json)
                tool_calls.append({"name": name, "args": args})
                removed_spans.append((m.start(), m.end()))
            except Exception:
                pass

    # 2. XML <tool_call> format (Hermes, Qwen, Claude):
    xml_pattern = re.compile(r'<tool_call>\s*([\s\S]*?)\s*</tool_call>')
    for m in xml_pattern.finditer(text):
        inner = m.group(1).strip()
        try:
            if inner.startswith("{"):
                data = json.loads(inner)
                name = data.get("name") or data.get("function")
                args = data.get("arguments") or data.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                if name in VALID_TOOLS:
                    tool_calls.append({"name": name, "args": args})
                    removed_spans.append((m.start(), m.end()))
                    continue
        except Exception:
            pass

        # Fallback to call:NAME{...} inside <tool_call>
        call_m = re.search(r'(?:call:)?([a-zA-Z0-9_]+)\s*(\{[\s\S]*\})', inner)
        if call_m and call_m.group(1) in VALID_TOOLS:
            try:
                args = json.loads(call_m.group(2))
                tool_calls.append({"name": call_m.group(1), "args": args})
                removed_spans.append((m.start(), m.end()))
            except Exception:
                pass

    # 3. Standard Kratos format: call:NAME{...} or NAME{...}
    pattern = re.compile(r'(?:call:)?([a-zA-Z0-9_]+)\s*\{')
    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            break

        # Skip if within an already extracted span
        if any(start <= m.start() < end for start, end in removed_spans):
            pos = m.end()
            continue

        fn_name = m.group(1)
        if fn_name in VALID_TOOLS:
            call_start = m.start()
            brace_start = m.end() - 1
            parsed_args, json_start, json_end = _extract_json_object(text, brace_start)
            if parsed_args is not None and json_end > json_start:
                tool_calls.append({"name": fn_name, "args": parsed_args})
                removed_spans.append((call_start, json_end))
                pos = json_end
                continue

        pos = m.end()

    # Reconstruct clean text excluding tool call segments
    clean_text = text
    if removed_spans:
        removed_spans.sort(key=lambda x: x[0])
        merged_spans = []
        for s, e in removed_spans:
            if not merged_spans or s > merged_spans[-1][1]:
                merged_spans.append([s, e])
            else:
                merged_spans[-1][1] = max(merged_spans[-1][1], e)

        clean_parts = []
        last_end = 0
        for start, end in merged_spans:
            clean_parts.append(text[last_end:start])
            last_end = end
        clean_parts.append(text[last_end:])
        clean_text = "".join(clean_parts).strip()
        # Clean any remaining special tokens or commentary headers
        clean_text = re.sub(r'<\|[^|]*\|>', '', clean_text)
        clean_text = re.sub(r'^(?:assistant\s*)?(?:commentary)?\s*', '', clean_text).strip()

    return clean_text, tool_calls


class BrainChatModel(BaseChatModel):
    """LangChain BaseChatModel backed by BrainClient."""
    model_name: str = DEFAULT_MODEL
    client: BrainClient = None

    def __init__(self, model: Optional[str] = None, client: Optional[BrainClient] = None, **kwargs):
        target_model = model or get_default_model()
        super().__init__(model_name=target_model, **kwargs)
        self.model_name = target_model
        self.client = client or BrainClient()

    @property
    def _llm_type(self) -> str:
        return "brain"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        dict_messages: List[Dict[str, Any]] = []
        system_instruction = None

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_instruction = msg.content
            elif isinstance(msg, HumanMessage):
                dict_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                dict_messages.append({"role": "assistant", "content": msg.content})
            else:
                dict_messages.append({"role": "user", "content": str(msg.content)})

        raw_output = self.client.generate(
            model=self.model_name,
            messages=dict_messages,
            system_instruction=system_instruction,
        )

        clean_text, parsed_tools = extract_tool_calls_from_text(raw_output)
        ai_message = AIMessage(content=clean_text or raw_output)
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        dict_messages: List[Dict[str, Any]] = []
        system_instruction = None

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_instruction = msg.content
            elif isinstance(msg, HumanMessage):
                dict_messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                dict_messages.append({"role": "assistant", "content": msg.content})
            else:
                dict_messages.append({"role": "user", "content": str(msg.content)})

        for chunk in self.client.stream(
            model=self.model_name,
            messages=dict_messages,
            system_instruction=system_instruction,
        ):
            if chunk:
                generation_chunk = ChatGenerationChunk(message=AIMessageChunk(content=chunk))
                if run_manager:
                    run_manager.on_llm_new_token(chunk, chunk=generation_chunk)
                yield generation_chunk


# Backward compatibility alias
OmnirouteChatModel = BrainChatModel
