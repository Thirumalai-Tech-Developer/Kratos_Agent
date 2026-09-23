"""Validated tool registry and execution boundary.

All tools cross this boundary, including MCP tools.  A rejected or failed call is
returned as a ToolResult, never raised into the loop and never discarded.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List
import inspect
import json
import time

from .runtime_contracts import ToolCall, ToolPermission, ToolResult, ToolSpec


@dataclass
class RegisteredTool:
    spec: ToolSpec
    handler: Callable[..., str]


from enum import Enum


class ToolCategory(str, Enum):
    GENERAL = "GENERAL"
    CODE = "CODE"
    BROWSER = "BROWSER"
    COMPUTER = "COMPUTER"
    FILES = "FILES"
    SYSTEM = "SYSTEM"
    MEMORY = "MEMORY"


def categorize_tool(name: str) -> ToolCategory:
    """Classifies a tool into one of the 7 core categories."""
    n = name.lower()
    if any(k in n for k in ("browser", "playwright", "fetch_url", "google_search", "web_")):
        return ToolCategory.BROWSER
    if any(k in n for k in ("gui_", "mouse_", "window_", "computer_click", "computer_type", "computer_press", "computer_find", "computer_observe", "computer_inspect", "computer_launch_app")):
        return ToolCategory.COMPUTER
    if any(k in n for k in ("file", "directory", "grep", "read_file", "write_file", "edit_file")):
        return ToolCategory.FILES
    if any(k in n for k in ("terminal", "command", "git_", "test", "pytest", "code", "python", "compile")):
        return ToolCategory.CODE
    if any(k in n for k in ("memory", "recall", "remember", "workflow")):
        return ToolCategory.MEMORY
    if any(k in n for k in ("process", "clipboard", "system", "device", "audio", "camera")):
        return ToolCategory.SYSTEM
    return ToolCategory.GENERAL


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: Callable[..., str]) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def search(self, query: str, context: Optional[Any] = None, max_results: int = 15) -> List[Dict[str, Any]]:
        """Performs semantic search across the tool catalog and returns top 5-15 candidate tool schemas."""
        from kratos_agent.tools.discovery import get_tool_search
        ts = get_tool_search()
        ctx_dict = {"context": context} if context else {}
        matched = ts.search(query, context=ctx_dict, max_results=max_results)
        matched_names = {m.name for m in matched}

        results = []
        for name in matched_names:
            item = self._tools.get(name)
            if item:
                results.append({
                    "type": "function",
                    "function": {
                        "name": item.spec.name,
                        "description": item.spec.description,
                        "parameters": item.spec.parameters,
                    },
                    "source": item.spec.source,
                })
        return results

    def get_tools(self, context: Optional[Any] = None, categories: Optional[List[str]] = None, max_tools: int = 15) -> List[Dict[str, Any]]:
        """Dynamically loads and returns only relevant tool schemas (5-15 tools) for the given context."""
        if context:
            ctx_str = str(context)
            searched = self.search(ctx_str, context=context, max_results=max_tools)
            if searched:
                return searched

        selected_cats = set()
        if categories:
            selected_cats.update(c.upper() for c in categories)

        if context:
            ctx_str = str(context).lower()
            if any(w in ctx_str for w in ("browser", "chrome", "web", "url", "navigate", "youtube")):
                selected_cats.add(ToolCategory.BROWSER.value)
                selected_cats.add(ToolCategory.COMPUTER.value)
            if any(w in ctx_str for w in ("click", "type", "press", "window", "gui", "desktop", "app", "button")):
                selected_cats.add(ToolCategory.COMPUTER.value)
                selected_cats.add(ToolCategory.SYSTEM.value)
            if any(w in ctx_str for w in ("file", "read", "write", "edit", "directory", "grep")):
                selected_cats.add(ToolCategory.FILES.value)
                selected_cats.add(ToolCategory.CODE.value)
            if any(w in ctx_str for w in ("terminal", "command", "git", "run", "test", "pytest")):
                selected_cats.add(ToolCategory.CODE.value)
                selected_cats.add(ToolCategory.FILES.value)
                selected_cats.add(ToolCategory.SYSTEM.value)
            if any(w in ctx_str for w in ("memory", "recall", "remember", "preference", "workflow")):
                selected_cats.add(ToolCategory.MEMORY.value)

        # Always include GENERAL category
        selected_cats.add(ToolCategory.GENERAL.value)

        results = []
        for item in self._tools.values():
            cat = categorize_tool(item.spec.name).value
            if not categories and not context:
                # No filter provided, return all
                results.append({"type": "function", "function": {"name": item.spec.name, "description": item.spec.description, "parameters": item.spec.parameters}, "source": item.spec.source})
            elif cat in selected_cats:
                results.append({"type": "function", "function": {"name": item.spec.name, "description": item.spec.description, "parameters": item.spec.parameters}, "source": item.spec.source})
        return results[:max_tools] if (categories or context) else results

    def schemas(self, categories: Optional[List[str]] = None, context: Optional[Any] = None) -> List[Dict[str, Any]]:
        if categories or context:
            return self.get_tools(context=context, categories=categories)
        return [
            {"type": "function", "function": {"name": item.spec.name, "description": item.spec.description, "parameters": item.spec.parameters}, "source": item.spec.source}
            for item in self._tools.values()
        ]


    def specs(self) -> List[ToolSpec]:
        return [item.spec for item in self._tools.values()]

    def execute(self, call: ToolCall, allow: Callable[[ToolSpec, Dict[str, Any]], tuple[bool, str]]) -> ToolResult:
        started = time.monotonic()
        registered = self._tools.get(call.name)
        if registered is None:
            return ToolResult(call.call_id, call.name, f"Unknown tool: {call.name}", is_error=True)
        valid, reason = self._validate(registered.spec, call.arguments)
        if not valid:
            return ToolResult(call.call_id, call.name, reason, is_error=True)
            
        forbidden, forbid_reason = self._forbidden_target(call)
        if forbidden:
            return ToolResult(call.call_id, call.name, f"Forbidden target: {forbid_reason}", is_error=True)
            
        allowed, reason = allow(registered.spec, call.arguments)
        if not allowed:
            return ToolResult(call.call_id, call.name, f"Tool execution requires approval: {reason}", is_error=True)
        try:
            result = registered.handler(**call.arguments)
            return ToolResult(call.call_id, call.name, str(result), duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return ToolResult(call.call_id, call.name, f"Tool failed: {type(exc).__name__}: {exc}", is_error=True, duration_ms=int((time.monotonic() - started) * 1000))

    @staticmethod
    def _validate(spec: ToolSpec, arguments: Dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(arguments, dict):
            return False, "Tool arguments must be an object."
        schema = spec.parameters or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        missing = [name for name in required if name not in arguments]
        unknown = [name for name in arguments if name not in properties]
        if missing:
            return False, f"Missing required arguments: {', '.join(missing)}"
        if unknown and schema.get("additionalProperties") is False:
            return False, f"Unknown arguments: {', '.join(unknown)}"
        return True, "allowed"

    def _forbidden_target(self, call: ToolCall) -> tuple[bool, str]:
        """Self-preservation invariants that block destructive actions against Kratos itself."""
        args_str = json.dumps(call.arguments).lower()
        if call.name in ("run_terminal_command", "app_launch", "system_elevate"):
            if any(x in args_str for x in ["taskkill /f /im kratos", "killall kratos", "format c:", "mkfs"]):
                return True, "Cannot kill Kratos or format disks."
            if "rm -rf /" in args_str or "del /s /q c:\\windows" in args_str:
                return True, "Cannot delete critical OS folders."
        if call.name in ("write_file", "edit_file", "file_delete"):
            target = str(call.arguments.get("file_path", "")).lower()
            if ".kratos/trace" in target or ".kratos/audit" in target or ".kratos/snapshots" in target:
                return True, "Cannot modify or delete Kratos audit/snapshot logs."
            if target.startswith("c:\\windows") or target.startswith("/bin") or target.startswith("/usr"):
                return True, "Cannot write to critical OS folders directly."
            if target.startswith("\\\\.\\physicaldrive") or target.startswith("/dev/sd") or target.startswith("/dev/nvme"):
                return True, "Cannot write to raw block devices."
        return False, ""



def legacy_tool_registry(workspace: Path) -> ToolRegistry:
    """Adapt existing curated Kratos tools without exposing arbitrary Python code."""
    from kratos_agent.utils import tools as legacy
    from kratos_agent.utils import computer_tools
    # Tools are shipped with Kratos; the workspace is the *target* project and
    # must not be required to contain the Kratos source tree.
    manifest = Path(__file__).resolve().parents[1] / "utils" / "tools_list.json"
    data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"tools": []}
    registry = ToolRegistry()
    for item in data.get("tools", []):
        function_name = item.get("func_name")
        handler = getattr(legacy, function_name, None)
        if handler is None:
            handler = getattr(computer_tools, function_name, None)
        if handler is None:
            continue
        name = item.get("name", function_name)
        permission = _permission_for(name)
        params = item.get("parameters") or _signature_schema(handler)
        registry.register(
            ToolSpec(name=name, description=item.get("description", ""), parameters=params, permission=permission),
            handler,
        )
    return registry


def _permission_for(name: str) -> ToolPermission:
    if name in {
        "read_file", "list_directory", "grep_search", "git_status", "git_diff",
        "read_skill", "list_skills", "read_memory", "todo_write", "exit_plan_mode",
        "computer_observe", "computer_inspect", "computer_find", "computer_screenshot",
        "computer_clipboard_read", "computer_window_list", "computer_browser_read",
        "computer_file_list", "computer_file_read", "computer_process_list", "gui_find"
    }:
        return ToolPermission.READ
    if name in {"write_file", "edit_file", "save_memory", "clear_memory", "computer_file_write", "computer_clipboard_write"}:
        return ToolPermission.WRITE
    if name.startswith("git_"):
        return ToolPermission.GIT
    if name in {"fetch_url", "google_search", "computer_browser_navigate", "browser_download", "download_file", "download_many"}:
        return ToolPermission.NETWORK
    return ToolPermission.EXECUTE


def _signature_schema(handler: Callable[..., Any]) -> Dict[str, Any]:
    properties, required = {}, []
    for parameter in inspect.signature(handler).parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        properties[parameter.name] = {"type": "string", "description": parameter.name.replace("_", " ")}
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
