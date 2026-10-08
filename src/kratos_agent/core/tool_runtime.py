"""Validated tool registry and execution boundary.

All tools cross this boundary, including MCP tools.  A rejected or failed call is
returned as a ToolResult, never raised into the loop and never discarded.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import inspect
import json
import re
import time
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from .runtime_contracts import ToolCall, ToolPermission, ToolResult, ToolSpec


def _reject_external_schema(uri: str):
    """Tool schemas may reference their own definitions, never fetch remote data."""
    raise NoSuchResource(ref=uri)


_LOCAL_SCHEMA_REGISTRY = Registry(retrieve=_reject_external_schema)


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
    if n.startswith(("mcp__computer-use__", "mcp__computer_use__")):
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


TOOL_ALIASES: dict[str, str] = {
    # Terminal & Command execution
    "terminal": "run_terminal_command",
    "terminal_run_command": "run_terminal_command",
    "run_terminal_cmd": "run_terminal_command",
    "run_command": "run_terminal_command",
    "run_cmd": "run_terminal_command",
    "terminal_command": "run_terminal_command",
    "exec_command": "run_terminal_command",
    "execute_command": "run_terminal_command",
    "execute_terminal_command": "run_terminal_command",
    "terminal_exec": "run_terminal_command",
    "shell": "run_terminal_command",
    "bash": "run_terminal_command",
    "sh": "run_terminal_command",
    "cmd": "run_terminal_command",
    "powershell": "run_terminal_command",
    "run_shell": "run_terminal_command",
    "exec": "run_terminal_command",

    # File Writing & Creation
    "create_file": "write_file",
    "save_file": "write_file",
    "new_file": "write_file",
    "write_to_file": "write_file",
    "file_write": "write_file",

    # File Reading & Viewing
    "read_file": "read_file",
    "view_file": "read_file",
    "open_file": "read_file",
    "cat": "read_file",
    "file_read": "read_file",

    # File Editing
    "edit_file": "edit_file",
    "modify_file": "edit_file",
    "update_file": "edit_file",
    "patch_file": "edit_file",
    "replace_file_content": "edit_file",
    "multi_replace_file_content": "edit_file",

    # Directory Listing
    "list_directory": "list_directory",
    "list_dir": "list_directory",
    "list_files": "list_directory",
    "ls": "list_directory",
    "dir": "list_directory",

    # Search & Grep
    "grep": "grep_search",
    "grep_search": "grep_search",
    "search_files": "grep_search",
    "find_in_files": "grep_search",
    "find_files": "grep_search",

    # Browser Navigation & Reading
    "browser_navigate": "browser_navigate",
    "navigate_browser": "browser_navigate",
    "browser_goto": "browser_navigate",
    "goto_url": "browser_navigate",
    "open_url": "browser_navigate",
    "browser_read": "browser_read",
    "read_browser": "browser_read",
    "read_page": "browser_read",
    "browser_download": "browser_download",
    "download_file": "browser_download",
}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: Callable[..., str]) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool | None:
        if not name:
            return None
        raw = name.strip()
        if raw in self._tools:
            return self._tools[raw]
        canonical = TOOL_ALIASES.get(raw.lower())
        if canonical and canonical in self._tools:
            return self._tools[canonical]
        for k, v in self._tools.items():
            if k.lower() in (raw.lower(), (canonical or "").lower()):
                return v
        return None

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def search(self, query: str, context: Any | None = None, max_results: int = 15) -> list[dict[str, Any]]:
        """Performs semantic search across the tool catalog and returns top 5-15 candidate tool schemas."""
        from kratos_agent.tools.discovery import get_tool_search
        ts = get_tool_search()
        ctx_dict = {"context": context} if context else {}
        matched = ts.search(query, context=ctx_dict, max_results=max_results)
        matched_names = {m.name for m in matched}

        query_tokens = set(re.findall(r"\w+", query.lower()))
        dynamic_matches = []
        for name, item in self._tools.items():
            if item.spec.source == "builtin":
                continue
            searchable = f"{name} {item.spec.description} {item.spec.source}".lower()
            overlap = sum(token in searchable for token in query_tokens if len(token) > 2)
            if overlap:
                dynamic_matches.append((overlap, name, item))
        dynamic_matches.sort(key=lambda entry: (-entry[0], entry[1]))
        results = [
            {
                "type": "function",
                "function": {"name": item.spec.name, "description": item.spec.description, "parameters": item.spec.parameters},
                "source": item.spec.source,
            }
            for _, _, item in dynamic_matches[:max_results]
        ]
        for name in matched_names:
            item = self._tools.get(name)
            if item and name not in {entry[1] for entry in dynamic_matches}:
                results.append({
                    "type": "function",
                    "function": {
                        "name": item.spec.name,
                        "description": item.spec.description,
                        "parameters": item.spec.parameters,
                    },
                    "source": item.spec.source,
                })
        return results[:max_results]

    def get_tools(self, context: Any | None = None, categories: list[str] | None = None, max_tools: int = 35) -> list[dict[str, Any]]:
        """Dynamically loads and returns only relevant tool schemas for the given context."""
        searched: list[dict[str, Any]] = []
        if context:
            ctx_str = str(context)
            searched = self.search(ctx_str, context=context, max_results=max_tools)

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
            if any(w in ctx_str for w in (
                "make", "create", "build", "develop", "code", "scaffold", "setup",
                "react", "tailwind", "vite", "npm", "node", "folder", "project",
                "script", "install", "html", "css", "js", "ts", "python", "site",
                "website", "app", "server", "api", "component", "ui", "game"
            )):
                selected_cats.add(ToolCategory.CODE.value)
                selected_cats.add(ToolCategory.FILES.value)
                selected_cats.add(ToolCategory.SYSTEM.value)

        # Always include GENERAL category
        selected_cats.add(ToolCategory.GENERAL.value)

        def schema(item: RegisteredTool) -> dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": item.spec.name,
                    "description": item.spec.description,
                    "parameters": item.spec.parameters,
                },
                "source": item.spec.source,
            }

        if not categories and not context:
            return [schema(item) for item in self._tools.values()]

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Core developer tools are available for coding, file, and system tasks.
        # General tools (such as todo_write) must not pull file and shell tools
        # into unrelated browser or conversation requests.
        core_essential_names = [
            "run_terminal_command",
            "write_file",
            "edit_file",
            "read_file",
            "list_directory",
            "grep_search",
        ]
        if any(cat in selected_cats for cat in (ToolCategory.CODE.value, ToolCategory.FILES.value, ToolCategory.SYSTEM.value)):
            for core_name in core_essential_names:
                item = self._tools.get(core_name)
                if item and core_name not in seen:
                    results.append(schema(item))
                    seen.add(core_name)

        # Semantic search ranked matches
        for result in searched:
            name = result.get("function", {}).get("name")
            item = self._tools.get(name)
            if item and categorize_tool(name).value in selected_cats and name not in seen:
                results.append(schema(item))
                seen.add(name)

        # Category tools
        for item in self._tools.values():
            name = item.spec.name
            if categorize_tool(name).value in selected_cats and name not in seen:
                results.append(schema(item))
                seen.add(name)

        if not (categories or context):
            return results

        # Ensure core essential tools are never truncated if results exceed max_tools
        if len(results) > max_tools:
            capped = results[:max_tools]
            capped_names = {r.get("function", {}).get("name") for r in capped}
            for core_name in core_essential_names:
                if core_name in seen and core_name not in capped_names:
                    item = self._tools.get(core_name)
                    if item:
                        capped.append(schema(item))
            return capped
        return results

    def schemas(self, categories: list[str] | None = None, context: Any | None = None) -> list[dict[str, Any]]:
        if categories or context:
            return self.get_tools(context=context, categories=categories)
        return [
            {"type": "function", "function": {"name": item.spec.name, "description": item.spec.description, "parameters": item.spec.parameters}, "source": item.spec.source}
            for item in self._tools.values()
        ]


    def specs(self) -> list[ToolSpec]:
        return [item.spec for item in self._tools.values()]

    def execute(self, call: ToolCall, allow: Callable[[ToolSpec, dict[str, Any]], tuple[bool, str]]) -> ToolResult:
        started = time.monotonic()
        raw_name = (call.name or "").strip()
        canonical_name = TOOL_ALIASES.get(raw_name.lower(), raw_name)
        registered = self._tools.get(raw_name) or self._tools.get(canonical_name)
        if registered is None:
            # Case-insensitive scan fallback
            for name, tool in self._tools.items():
                if name.lower() in (raw_name.lower(), canonical_name.lower()):
                    registered = tool
                    break
        if registered is None:
            return ToolResult(call.call_id, call.name, f"Unknown tool: {call.name}", is_error=True)

        # Standardize call.name to registered canonical tool name for consistent logging & lifecycle tracking
        call.name = registered.spec.name

        if not isinstance(call.arguments, dict):
            return ToolResult(call.call_id, call.name, "Tool arguments must be an object.", is_error=True)

        # Normalize common parameter aliases across diverse LLM outputs
        schema = registered.spec.parameters if registered.spec.parameters is not None else {}
        if not isinstance(schema, dict) or not isinstance(schema.get("properties", {}), dict):
            return ToolResult(call.call_id, call.name, "Invalid tool parameter schema.", is_error=True)
        props = schema.get("properties", {})
        # Some models repeat the tool-call envelope inside the arguments object.
        # Preserve tools whose schema actually declares an arguments parameter.
        if "arguments" not in props and set(call.arguments) == {"arguments"} and isinstance(call.arguments["arguments"], dict):
            call.arguments = dict(call.arguments["arguments"])
        # Provider bookkeeping is not a shell/tool parameter.
        if "_nonce" not in props:
            call.arguments.pop("_nonce", None)
        if "file_path" in props and "file_path" not in call.arguments:
            for alt in ("path", "target_file", "filepath", "filename", "file", "dest", "destination"):
                if alt in call.arguments:
                    call.arguments["file_path"] = call.arguments.pop(alt)
                    break
        if "command" in props and "command" not in call.arguments:
            for alt in ("cmd", "script", "terminal_command", "terminal", "code", "input", "action"):
                if alt in call.arguments:
                    call.arguments["command"] = call.arguments.pop(alt)
                    break
        if "content" in props and "content" not in call.arguments:
            for alt in ("text", "data", "code", "body", "value"):
                if alt in call.arguments:
                    call.arguments["content"] = call.arguments.pop(alt)
                    break
        if "target_text" in props and "target_text" not in call.arguments:
            for alt in ("old_text", "find", "search", "target", "original"):
                if alt in call.arguments:
                    call.arguments["target_text"] = call.arguments.pop(alt)
                    break
        if "replacement_text" in props and "replacement_text" not in call.arguments:
            for alt in ("new_text", "replace", "replacement", "content", "text"):
                if alt in call.arguments:
                    call.arguments["replacement_text"] = call.arguments.pop(alt)
                    break
        if "directory_path" in props and "directory_path" not in call.arguments:
            for alt in ("path", "dir_path", "dir", "directory", "folder"):
                if alt in call.arguments:
                    call.arguments["directory_path"] = call.arguments.pop(alt)
                    break
        if "query" in props and "query" not in call.arguments:
            for alt in ("search", "q", "pattern", "text"):
                if alt in call.arguments:
                    call.arguments["query"] = call.arguments.pop(alt)
                    break
        if "pattern" in props and "pattern" not in call.arguments:
            for alt in ("query", "search", "regex"):
                if alt in call.arguments:
                    call.arguments["pattern"] = call.arguments.pop(alt)
                    break

        valid, reason = self._validate(registered.spec, call.arguments)
        if not valid:
            return ToolResult(call.call_id, call.name, reason, is_error=True)

        forbidden, forbid_reason = self._forbidden_target(call)
        if forbidden:
            try:
                from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
                if approval_gate.mode is not ApprovalMode.SOVEREIGN:
                    return ToolResult(call.call_id, call.name, f"Forbidden target: {forbid_reason}", is_error=True)
                approval_gate._audit.record(call.name, str(call.arguments), "SOVEREIGN_OVERRIDE", "sovereign")
            except Exception:
                return ToolResult(call.call_id, call.name, f"Forbidden target: {forbid_reason}", is_error=True)

        allowed, reason = allow(registered.spec, call.arguments)
        if not allowed:
            return ToolResult(call.call_id, call.name, f"Tool execution requires approval: {reason}", is_error=True)
        try:
            result = registered.handler(**call.arguments)
            content = str(result)
            is_error = call.name == "run_terminal_command" and _terminal_command_failed(content)
            return ToolResult(call.call_id, call.name, content, is_error=is_error, duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return ToolResult(call.call_id, call.name, f"Tool failed: {type(exc).__name__}: {exc}", is_error=True, duration_ms=int((time.monotonic() - started) * 1000))


    @staticmethod
    def _validate(spec: ToolSpec, arguments: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(arguments, dict):
            return False, "Tool arguments must be an object."
        schema = spec.parameters if spec.parameters is not None else {}
        if not isinstance(schema, dict):
            return False, "Invalid tool parameter schema."
        try:
            validator_class = validator_for(schema, default=Draft202012Validator)
            validator_class.check_schema(schema)
            # JSON decoders and Python handlers can otherwise accept NaN/Infinity.
            json.dumps(arguments, allow_nan=False)
            validator = validator_class(schema, registry=_LOCAL_SCHEMA_REGISTRY, format_checker=FormatChecker())
            error = next(validator.iter_errors(arguments), None)
        except SchemaError:
            return False, "Invalid tool parameter schema."
        except Unresolvable:
            return False, "Tool schema reference cannot be resolved locally."
        except (TypeError, ValueError, RecursionError):
            return False, "Tool arguments or schema cannot be validated as JSON."

        required = schema.get("required", [])
        properties = schema.get("properties", {})
        missing = [name for name in required if name not in arguments]
        unknown = [name for name in arguments if name not in properties]
        if missing:
            return False, f"Missing required arguments: {', '.join(missing)}"
        if unknown and schema.get("additionalProperties") is False:
            return False, f"Unknown arguments: {', '.join(unknown)}"
        if error is not None:
            # Do not include argument values (which may contain credentials) in errors.
            return False, f"Invalid tool arguments at {error.json_path}: failed {error.validator} validation."
        return True, "allowed"

    def _forbidden_target(self, call: ToolCall) -> tuple[bool, str]:
        """Return application-level target blocks outside Sovereign mode."""
        try:
            from kratos_agent.core.approval_mode import ApprovalMode, approval_gate
            if approval_gate.mode is ApprovalMode.SOVEREIGN:
                return False, ""
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)
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


def _terminal_command_failed(content: str) -> bool:
    """Promote structured and textual nonzero shell exits to tool errors."""
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        result = None
    if isinstance(result, dict) and result.get("ok") is False:
        return True
    match = re.search(
        r"(?im)^\s*(?:Exit Code:|Command exited with status)\s*(-?\d+)\.?\s*$",
        content,
    )
    return bool(match and int(match.group(1)) != 0)



def legacy_tool_registry(workspace: Path) -> ToolRegistry:
    """Adapt existing curated Kratos tools without exposing arbitrary Python code."""
    # Computer Control Subsystem tools live in dedicated modules.
    from kratos_agent.computer.tools import browser_tools, gui_tools, system_tools
    from kratos_agent.computer.tools import computer_tools as ccs_computer_tools
    from kratos_agent.utils import computer_tools
    from kratos_agent.utils import tools as legacy
    # Tools are shipped with Kratos; the workspace is the *target* project and
    # must not be required to contain the Kratos source tree.
    manifest = Path(__file__).resolve().parents[1] / "utils" / "tools_list.json"
    data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"tools": []}
    registry = ToolRegistry()
    for item in data.get("tools", []):
        function_name = item.get("func_name")
        name = item.get("name", function_name)
        # Pointer coordinates are outside Kratos' computer-use contract. Keep
        # legacy mouse helpers out of model-visible registries even when a
        # generated or stale catalog still contains them.
        if str(name or function_name or "").lower().startswith(("mouse_", "gui_mouse")) or str(name or function_name or "").lower() == "cursor_position":
            continue
        handler = getattr(legacy, function_name, None)
        if handler is None:
            handler = getattr(computer_tools, function_name, None)
        if handler is None:
            for module in (browser_tools, ccs_computer_tools, gui_tools, system_tools):
                handler = getattr(module, function_name, None)
                if handler is not None:
                    break
        if handler is None:
            continue
        permission = _permission_for(name)
        inferred = _signature_schema(handler)
        declared = item.get("parameters")
        params = json.loads(json.dumps(declared)) if declared else inferred
        # Older generated manifests flattened every parameter to string. Repair
        # those types from the bundled handler while retaining descriptions and limits.
        for argument, inferred_schema in inferred["properties"].items():
            prop = params.get("properties", {}).get(argument)
            if prop and prop.get("type") == "string" and inferred_schema.get("type") != "string" and ("type" in inferred_schema or "anyOf" in inferred_schema):
                prop.pop("type", None)
                prop.update({key: value for key, value in inferred_schema.items() if key != "description"})
        if name == "run_terminal_command":
            params = dict(params)
            params["properties"] = dict(params.get("properties", {}))
            params["properties"]["working_directory"] = {"type": "string", "description": "Process working directory; use the temporary directory for scratch scripts."}
            params["properties"]["argv"] = {"type": "array", "items": {"type": "string"}, "description": "Direct process arguments instead of a shell command."}
            params["required"] = []
            params["additionalProperties"] = False
        registry.register(
            ToolSpec(name=name, description=item.get("description", ""), parameters=params, permission=permission),
            handler,
        )
    from kratos_agent.jobs.tools import register_job_tools
    register_job_tools(registry, workspace)
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


def _signature_schema(handler: Callable[..., Any]) -> dict[str, Any]:
    properties, required = {}, []
    try:
        annotations = get_type_hints(handler)
    except (NameError, TypeError):
        annotations = {}
    for parameter in inspect.signature(handler).parameters.values():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        annotation = annotations.get(parameter.name, parameter.annotation)
        if annotation is inspect.Parameter.empty or isinstance(annotation, str):
            annotation = type(parameter.default) if parameter.default is not inspect.Parameter.empty else Any
        properties[parameter.name] = {**_annotation_schema(annotation), "description": parameter.name.replace("_", " ")}
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _annotation_schema(annotation: Any) -> dict[str, Any]:
    primitive = {str: "string", int: "integer", float: "number", bool: "boolean", type(None): "null"}
    if annotation in primitive:
        return {"type": primitive[annotation]}
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return {"anyOf": [_annotation_schema(value) for value in arguments]}
    if origin is Annotated:
        return _annotation_schema(arguments[0])
    if origin is Literal:
        return {"enum": list(arguments)}
    if origin is list or annotation is list:
        return {"type": "array", "items": _annotation_schema(arguments[0]) if arguments else {}}
    if origin is dict or annotation is dict:
        return {"type": "object", "additionalProperties": _annotation_schema(arguments[1]) if len(arguments) > 1 else {}}
    return {}
