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
        "fetch_url", "google_search", "self_tool_creator", "calculate_expression",
        "git_status", "git_diff", "git_commit", "git_push", "git_create_pr",
        "todo_write", "exit_plan_mode", "spawn_subagent", "list_skills", "read_skill",
        "replace_file_content", "multi_replace_file_content",
        "read_symbol", "search_symbol", "view_outline",
    }

    RESERVED_TOOL_NAMES = {
        "tool", "tools", "function", "call", "commentary", "channel", "constrain", "message",
        "i", "we", "you", "they", "he", "she", "it", "let", "now", "here", "then", "if", "so",
        "as", "to", "for", "and", "but", "or", "note", "example", "step", "task", "plan",
    }

    # 1. DeepSeek V3 / R1 <｜tool call begin｜> format:
    ds_tool_pattern = re.compile(
        r'<[｜|]tool call begin[｜|]>\s*(?:function)?\s*<[｜|]tool sep[｜|]>\s*([a-zA-Z0-9_]+)\s*(?:```(?:json)?\s*)?(\{[\s\S]*?\})\s*(?:```)?\s*<[｜|]tool call end[｜|]>',
        re.IGNORECASE
    )
    for m in ds_tool_pattern.finditer(text):
        if any(start <= m.start() < end for start, end in removed_spans):
            continue
        name = m.group(1)
        if name.lower() in RESERVED_TOOL_NAMES or len(name) < 2:
            continue
        try:
            args = json.loads(m.group(2))
            if name in VALID_TOOLS or name.isidentifier():
                tool_calls.append({"name": name, "args": args if isinstance(args, dict) else {}})
                removed_spans.append((m.start(), m.end()))
        except Exception:
            pass

    # 1b. DeepSeek DSML <｜｜DSML｜｜ invoke name="...">...<｜｜DSML｜｜ parameter name="...">...</｜｜DSML｜｜ parameter> format:
    dsml_invoke_pattern = re.compile(
        r'<[｜|]{1,2}DSML[｜|]{1,2}\s*invoke\s+name=["\']?([a-zA-Z0-9_]+)["\']?\s*>([\s\S]*?)(?:</[｜|]{1,2}DSML[｜|]{1,2}\s*invoke>|(?=<[｜|]{1,2}DSML[｜|]{1,2}\s*invoke)|$)',
        re.IGNORECASE
    )
    dsml_param_pattern = re.compile(
        r'<[｜|]{1,2}DSML[｜|]{1,2}\s*parameter\s+name=["\']?([a-zA-Z0-9_]+)["\']?[^>]*>([\s\S]*?)(?:</[｜|]{1,2}DSML[｜|]{1,2}\s*parameter>|(?=<[｜|]{1,2}DSML[｜|]{1,2}\s*parameter)|(?=</[｜|]{1,2}DSML[｜|]{1,2}\s*invoke>)|$)',
        re.IGNORECASE
    )
    for m in dsml_invoke_pattern.finditer(text):
        if any(start <= m.start() < end for start, end in removed_spans):
            continue
        tool_name = m.group(1)
        if tool_name.lower() in RESERVED_TOOL_NAMES or len(tool_name) < 2:
            continue
        params_body = m.group(2)
        args: Dict[str, Any] = {}
        for p in dsml_param_pattern.finditer(params_body):
            p_name = p.group(1)
            p_val = p.group(2).strip()
            # If value is valid JSON, parse it (e.g. objects, arrays, numbers)
            if (p_val.startswith("{") and p_val.endswith("}")) or (p_val.startswith("[") and p_val.endswith("]")):
                try:
                    args[p_name] = json.loads(p_val)
                    continue
                except Exception:
                    pass
            args[p_name] = p_val

        # Fallback: check if params body contains raw JSON object
        if not args:
            json_m = re.search(r'\{[\s\S]*?\}', params_body)
            if json_m:
                try:
                    parsed = json.loads(json_m.group(0))
                    if isinstance(parsed, dict):
                        args = parsed
                except Exception:
                    pass

        if tool_name in VALID_TOOLS or tool_name.isidentifier():
            tool_calls.append({"name": tool_name, "args": args})
            start_span = m.start()
            end_span = m.end()
            close_m = re.search(r'</[｜|]{1,2}DSML[｜|]{1,2}\s*invoke>', text[m.start():])
            if close_m:
                end_span = m.start() + close_m.end()
            pre_m = re.search(r'<[｜|]{1,2}DSML[｜|]{1,2}\s*calls>\s*$', text[:start_span], re.IGNORECASE)
            if pre_m:
                start_span = pre_m.start()
            post_m = re.match(r'\s*</[｜|]{1,2}DSML[｜|]{1,2}\s*calls>', text[end_span:], re.IGNORECASE)
            if post_m:
                end_span += post_m.end()
            removed_spans.append((start_span, end_span))

    # 2. DeepSeek DSML / Standard <tool> format:
    # <tool>{"name": "...", "arguments": {...}}</｜｜DSML｜｜ parameter></｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>
    # or <tool>{"name": "...", "arguments": {...}}</tool>
    tool_tag_pattern = re.compile(r'<tool>\s*(\{)', re.IGNORECASE)
    pos = 0
    while pos < len(text):
        m = tool_tag_pattern.search(text, pos)
        if not m:
            break
        start_idx = m.start()
        brace_idx = m.start(1)
        parsed_obj, json_start, json_end = _extract_json_object(text, brace_idx)
        if parsed_obj and isinstance(parsed_obj, dict):
            name = parsed_obj.get("name") or parsed_obj.get("function")
            args = parsed_obj.get("arguments") or parsed_obj.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            if name and (name in VALID_TOOLS or name.isidentifier()) and name not in RESERVED_TOOL_NAMES:
                tool_calls.append({"name": name, "args": args if isinstance(args, dict) else {}})
                end_span = json_end
                trailing_m = re.match(
                    r'(?:\s*</tool>|\s*</[｜|]{1,2}[^>]*[｜|]{1,2}\s*[^>]*>|\s*<[｜|]{1,2}[^>]*[｜|]{1,2}>)*',
                    text[json_end:],
                    re.IGNORECASE
                )
                if trailing_m:
                    end_span += trailing_m.end()
                removed_spans.append((start_idx, end_span))
                pos = end_span
                continue
        pos = m.end()

    # 2b. Markdown fenced JSON block: ```json {"name": "...", "arguments": {...}}
    json_block_pattern = re.compile(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```')
    for m in json_block_pattern.finditer(text):
        if any(start <= m.start() < end for start, end in removed_spans):
            continue
        try:
            data = json.loads(m.group(1))
            name = data.get("name") or data.get("function") or data.get("tool")
            args = data.get("arguments") or data.get("parameters") or data.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            if name and (name in VALID_TOOLS or (name.isidentifier() and len(name) >= 2)) and name.lower() not in RESERVED_TOOL_NAMES:
                tool_calls.append({"name": name, "args": args})
                removed_spans.append((m.start(), m.end()))
        except Exception:
            pass

    # 2c. Standalone JSON with "name" and "arguments"
    raw_json_pattern = re.compile(r'\{[\s\n]*"(?:name|function|tool)"\s*:\s*"([a-zA-Z0-9_]+)"[\s\S]*?\}')
    pos = 0
    while pos < len(text):
        m = raw_json_pattern.search(text, pos)
        if not m:
            break
        if any(start <= m.start() < end for start, end in removed_spans):
            pos = m.end()
            continue
        parsed_obj, json_start, end_span = _extract_json_object(text, m.start())
        if parsed_obj and isinstance(parsed_obj, dict):
            name = parsed_obj.get("name") or parsed_obj.get("function") or parsed_obj.get("tool")
            args = parsed_obj.get("arguments") or parsed_obj.get("parameters") or parsed_obj.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            if name and (name in VALID_TOOLS or (name.isidentifier() and len(name) >= 2)) and name.lower() not in RESERVED_TOOL_NAMES:
                tool_calls.append({"name": name, "args": args})
                removed_spans.append((json_start, end_span))
                pos = end_span
                continue
        pos = m.end()

    # 3. Harmony / OpenAI OSS / ChatML channel commentary format:
    harmony_pattern = re.compile(
        r'(?:<[|｜][^>|｜]*[|｜]>\s*)+(?:to=call:|call:)?([a-zA-Z0-9_]+)[\s\S]*?(?:<[|｜]message[|｜]>|```(?:json)?|\s*)\s*(\{[\s\S]*?\})\s*(?:<[|｜]call[|｜]>|```)?'
    )
    for m in harmony_pattern.finditer(text):
        if any(start <= m.start() < end for start, end in removed_spans):
            continue
        name = m.group(1)
        if name.lower() in RESERVED_TOOL_NAMES or len(name) < 2:
            continue
        if name in VALID_TOOLS or (name.isidentifier() and len(name) >= 2):
            try:
                raw_json = m.group(2)
                args = json.loads(raw_json)
                tool_calls.append({"name": name, "args": args})
                removed_spans.append((m.start(), m.end()))
            except Exception:
                pass

    # 4. XML <tool_call> format (Hermes, Qwen, Claude):
    xml_pattern = re.compile(r'<tool_call>\s*([\s\S]*?)\s*</tool_call>')
    for m in xml_pattern.finditer(text):
        if any(start <= m.start() < end for start, end in removed_spans):
            continue
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
                if name and (name in VALID_TOOLS or (name.isidentifier() and len(name) >= 2)) and name.lower() not in RESERVED_TOOL_NAMES:
                    tool_calls.append({"name": name, "args": args})
                    removed_spans.append((m.start(), m.end()))
                    continue
        except Exception:
            pass

        # Fallback to call:NAME{...} inside <tool_call>
        call_m = re.search(r'(?:call:)?([a-zA-Z0-9_]+)\s*(\{[\s\S]*\})', inner)
        if call_m:
            c_name = call_m.group(1)
            if c_name.lower() not in RESERVED_TOOL_NAMES and len(c_name) >= 2 and (c_name in VALID_TOOLS or c_name.isidentifier()):
                try:
                    args = json.loads(call_m.group(2))
                    tool_calls.append({"name": c_name, "args": args})
                    removed_spans.append((m.start(), m.end()))
                except Exception:
                    pass

    # 5. Standard Kratos format: call:NAME{...} or NAME{...}
    pattern = re.compile(r'(call:)?([a-zA-Z0-9_]+)\s*\{')
    pos = 0
    while pos < len(text):
        m = pattern.search(text, pos)
        if not m:
            break

        # Skip if within an already extracted span
        if any(start <= m.start() < end for start, end in removed_spans):
            pos = m.end()
            continue

        has_call_prefix = bool(m.group(1))
        fn_name = m.group(2)

        # Never treat single letters or common English words as tools
        if len(fn_name) < 2 or fn_name.lower() in RESERVED_TOOL_NAMES:
            pos = m.end()
            continue

        # If explicit call: prefix, allow valid identifier; otherwise require known tool in VALID_TOOLS
        is_valid_tool = (has_call_prefix and fn_name.isidentifier()) or (fn_name in VALID_TOOLS)
        if is_valid_tool:
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
        clean_text = re.sub(r'<[｜|]{1,2}[^>]*[｜|]{1,2}>', '', clean_text)
        clean_text = re.sub(r'</[｜|]{1,2}[^>]*[｜|]{1,2}>', '', clean_text)
        clean_text = re.sub(r'</?(?:tool|tools)>', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'^(?:assistant\s*)?(?:commentary)?\s*', '', clean_text).strip()

    # Deduplicate identical tool calls
    unique_tool_calls = []
    seen = set()
    for tc in tool_calls:
        key = (tc.get("name"), json.dumps(tc.get("args", {}), sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique_tool_calls.append(tc)

    return clean_text, unique_tool_calls


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
