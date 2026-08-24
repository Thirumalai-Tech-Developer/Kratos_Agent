from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Type, Union

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.base import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from kratos_agent.antigravity.accounts import AccountPool, PUBLIC_MODELS
from kratos_agent.antigravity.client import AntigravityClient
from kratos_agent.antigravity.gemini_direct import GeminiKeyPool

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
                raw_cmd = text[start_idx:end_idx]
                return {"name": "run_terminal_command", "args": {"command": _clean_command_payload(raw_cmd)}}
        cmd_m2 = re.search(r'"(?:command|direct_command|package_name)"\s*:\s*"(.*?)"', text, re.DOTALL)
        if cmd_m2:
            return {"name": "run_terminal_command", "args": {"command": _clean_command_payload(cmd_m2.group(1))}}

    if "google_search" in text:
        q_m = re.search(r'"query"\s*:\s*"(.*?)"', text, re.DOTALL)
        if q_m:
            return {"name": "google_search", "args": {"query": q_m.group(1)}}

    return None

def extract_tool_calls_from_text(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parses JSON, markdown, or call:tool_name blocks produced by the model."""
    tool_calls = []
    if not text:
        return text, tool_calls

    # 1. Match Google Cloud Code call:tool_name format
    mfc_match = re.search(r"call:([a-zA-Z0-9_]+)\s*(.*)", text, re.DOTALL)
    if mfc_match:
        tool_name = mfc_match.group(1).strip()
        body = mfc_match.group(2).strip()
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1].strip()

        args = {}
        if tool_name == "write_file":
            fp = "script.py"
            fp_m = re.search(r'(?<![a-zA-Z0-9_])file_path\s*[:=]\s*(?:[rfbRFB]#*|#*)?["\']?([^"\',\s\n\(\)]+)', body)
            if fp_m:
                fp = clean_file_path(fp_m.group(1))
                if not fp or fp in ("r#", "r", "#"):
                    fp = "script.py"
            c_start_m = re.search(r'(?<![a-zA-Z0-9_])content\s*[:=]\s*["\']?', body)
            if c_start_m:
                idx = c_start_m.end()
                fp_pos = body.find("file_path", idx)
                if fp_pos > idx:
                    raw_c = body[idx:fp_pos].rstrip('", \t\n')
                else:
                    raw_c = body[idx:].rstrip('"} \t\n')
                cleaned = raw_c.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
                tool_calls.append({
                    "name": "write_file",
                    "args": {"file_path": fp, "content": cleaned},
                    "id": str(uuid.uuid4())
                })
                return text, tool_calls

        if tool_name == "run_terminal_command":
            cmd_start_m = re.search(r'(?<![a-zA-Z0-9_])(?:command|direct_command|package_name)\s*[:=]\s*["\']?', body)
            raw_cmd = body[cmd_start_m.end():] if cmd_start_m else body
            tool_calls.append({
                "name": "run_terminal_command",
                "args": {"command": _clean_command_payload(raw_cmd)},
                "id": str(uuid.uuid4())
            })
            return text, tool_calls

        # Generic parameter extraction
        pairs = re.findall(r'([a-zA-Z0-9_]+)\s*[:=]\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,]+))', body)
        if pairs:
            for k, v1, v2, v3 in pairs:
                val = v1 or v2 or v3 or ""
                args[k.strip()] = val.strip()
        if not args and body:
            args = {"query": body} if "search" in tool_name else {"command": _clean_command_payload(body)}
        if "command" in args:
            args["command"] = _clean_command_payload(args["command"])
        tool_calls.append({
            "name": tool_name,
            "args": args,
            "id": str(uuid.uuid4())
        })
        return text, tool_calls

    # 2. Match ```json ... ``` blocks
    json_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block, strict=False)
            tool_name = data.get("tool") or data.get("name") or data.get("function")
            args = data.get("args") or data.get("arguments") or data.get("parameters") or {}
            if tool_name:
                if isinstance(args, str):
                    try:
                        args = json.loads(args, strict=False)
                    except Exception:
                        args = {"query": args} if "search" in tool_name else {"command": _clean_command_payload(args)}
                if "command" in args:
                    args["command"] = _clean_command_payload(args["command"])
                if "file_path" in args:
                    args["file_path"] = re.sub(r'^[rfbRFB]?["\']|["\']$', '', str(args["file_path"]).strip())
                tool_calls.append({
                    "name": str(tool_name).strip(),
                    "args": args if isinstance(args, dict) else {},
                    "id": str(uuid.uuid4())
                })
        except Exception:
            fallback = _fallback_extract_tool_call(block)
            if fallback:
                fallback["id"] = str(uuid.uuid4())
                tool_calls.append(fallback)

    # 3. Match any embedded JSON object containing tool/name/function using brace balance
    if not tool_calls:
        start_indices = [m.start() for m in re.finditer(r'\{', text)]
        for start in start_indices:
            depth = 0
            for end in range(start, len(text)):
                if text[end] == '{':
                    depth += 1
                elif text[end] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:end+1]
                        try:
                            data = json.loads(candidate, strict=False)
                            tool_name = data.get("tool") or data.get("name") or data.get("function")
                            args = data.get("args") or data.get("arguments") or data.get("parameters") or {}
                            if tool_name:
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args, strict=False)
                                    except Exception:
                                        args = {"query": args} if "search" in tool_name else {"command": _clean_command_payload(args)}
                                if "command" in args:
                                    args["command"] = _clean_command_payload(args["command"])
                                if "file_path" in args:
                                    args["file_path"] = re.sub(r'^[rfbRFB]?["\']|["\']$', '', str(args["file_path"]).strip())
                                tool_calls.append({
                                    "name": str(tool_name).strip(),
                                    "args": args if isinstance(args, dict) else {},
                                    "id": str(uuid.uuid4())
                                })
                        except Exception:
                            fallback = _fallback_extract_tool_call(candidate)
                            if fallback:
                                fallback["id"] = str(uuid.uuid4())
                                tool_calls.append(fallback)
                        break
            if tool_calls:
                break

    # 4. Global fallback regex if braces or formatting was broken
    if not tool_calls:
        fallback = _fallback_extract_tool_call(text)
        if fallback:
            fallback["id"] = str(uuid.uuid4())
            tool_calls.append(fallback)

    # 5. Match function call syntax: tool_name(arg="value")
    if not tool_calls:
        fn_match = re.search(r"(\b(?:write_file|read_file|google_search|run_terminal_command|self_tool_creator|calculate_expression|reverse_words|search_job)\b)\s*\((.*?)\)", text, re.DOTALL)
        if fn_match:
            fn_name = fn_match.group(1)
            raw_args = fn_match.group(2).strip()
            str_match = re.search(r"""(?:query|command|expression|sentence|input|content)?\s*=?\s*["'](.*?)["']""", raw_args, re.DOTALL)
            val = str_match.group(1) if str_match else raw_args
            arg_key = "sentence" if "reverse" in fn_name else ("command" if "command" in fn_name else ("expression" if "calculate" in fn_name else "query"))
            tool_calls.append({
                "name": fn_name,
                "args": {arg_key: val},
                "id": str(uuid.uuid4())
            })

    return text, tool_calls

def _convert_messages_to_contents(messages: List[BaseMessage]) -> Tuple[List[Dict[str, Any]], str]:
    """Converts LangChain message history to valid Google Generative AI contents with role alternation."""
    contents = []
    sys_prompt = ""

    for msg in messages:
        if isinstance(msg, SystemMessage):
            sys_prompt += ("\n" + str(msg.content) if sys_prompt else str(msg.content))
        elif isinstance(msg, HumanMessage):
            text = str(msg.content).strip() or " "
            contents.append({"role": "user", "parts": [{"text": text}]})
        elif isinstance(msg, AIMessage):
            parts = []
            if msg.content:
                parts.append({"text": str(msg.content)})
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append({"functionCall": {"name": tc["name"], "args": tc.get("args", {})}})
            if not parts:
                parts = [{"text": " "}]
            contents.append({"role": "model", "parts": parts})
        elif isinstance(msg, (ToolMessage, FunctionMessage)):
            text = str(msg.content).strip() or "Completed"
            name = getattr(msg, "name", None) or "tool"
            contents.append({
                "role": "user",
                "parts": [{"text": f"Output of tool '{name}':\n{text}\n\nUse this tool output to provide the final answer."}]
            })
        elif isinstance(msg, ChatMessage):
            role = "model" if msg.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": str(msg.content) or " "}]})

    # Merge consecutive messages with the same role
    merged_contents = []
    for c in contents:
        if merged_contents and merged_contents[-1]["role"] == c["role"]:
            merged_contents[-1]["parts"].extend(c["parts"])
        else:
            merged_contents.append(c)

    return merged_contents or [{"role": "user", "parts": [{"text": " "}]}], sys_prompt

class AntigravityChatModel(BaseChatModel):
    """Unified in-process LangChain chat model backed by native Antigravity client & Gemini key pool."""
    model_name: str = "gemini-3.6-flash-high"
    client: Optional[Any] = None
    gemini_pool: Optional[Any] = None

    def __init__(self, model: str = "gemini-3.6-flash-high", pool: Optional[AccountPool] = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.model_name = model
        self.client = AntigravityClient(pool=pool)
        self.gemini_pool = GeminiKeyPool()

    @property
    def _llm_type(self) -> str:
        return "antigravity"

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type, Callable, BaseTool]],
        *,
        tool_choice: Optional[Union[Dict[str, Any], bool, str]] = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        formatted_tools = [convert_to_openai_tool(t) if not isinstance(t, dict) else t for t in tools]
        return self.bind(tools=formatted_tools, tool_choice=tool_choice, **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        contents, sys_prompt = _convert_messages_to_contents(messages)
        bound_tools = kwargs.get("tools")

        reply_content = ""
        tool_calls = []

        msg_dicts = []
        for c in contents:
            msg_dicts.append({
                "role": "assistant" if c["role"] == "model" else "user",
                "content": "".join([p.get("text", "") for p in c["parts"] if "text" in p])
            })
        
        try:
            raw_reply = self.client.generate(model=self.model_name, messages=msg_dicts, system_instruction=sys_prompt or None)
            reply_content, tool_calls = extract_tool_calls_from_text(raw_reply)
            if tool_calls:
                reply_content = ""
            elif raw_reply:
                reply_content = raw_reply
        except Exception:
            if self.gemini_pool and self.gemini_pool.api_keys:
                try:
                    res = self.gemini_pool.generate(
                        model=self.model_name,
                        contents=contents,
                        system_instruction=sys_prompt or None,
                        tools=bound_tools
                    )
                    tool_calls = res.get("tool_calls", [])
                    reply_content = "" if tool_calls else res.get("content", "")
                except Exception:
                    pass

        ai_message = AIMessage(content=reply_content, tool_calls=tool_calls)
        generation = ChatGeneration(message=ai_message)
        return ChatResult(generations=[generation])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        contents, sys_prompt = _convert_messages_to_contents(messages)
        msg_dicts = []
        for c in contents:
            msg_dicts.append({
                "role": "assistant" if c["role"] == "model" else "user",
                "content": "".join([p.get("text", "") for p in c["parts"] if "text" in p])
            })
        for chunk in self.client.stream(model=self.model_name, messages=msg_dicts, system_instruction=sys_prompt or None):
            cg = ChatGenerationChunk(message=AIMessageChunk(content=chunk))
            if run_manager:
                run_manager.on_llm_new_token(chunk, chunk=cg)
            yield cg
