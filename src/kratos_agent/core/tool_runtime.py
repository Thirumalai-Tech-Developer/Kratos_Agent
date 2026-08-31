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


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: Callable[..., str]) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def schemas(self) -> List[Dict[str, Any]]:
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


def legacy_tool_registry(workspace: Path) -> ToolRegistry:
    """Adapt existing curated Kratos tools without exposing arbitrary Python code."""
    from kratos_agent.utils import tools as legacy
    # Tools are shipped with Kratos; the workspace is the *target* project and
    # must not be required to contain the Kratos source tree.
    manifest = Path(__file__).resolve().parents[1] / "utils" / "tools_list.json"
    data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"tools": []}
    registry = ToolRegistry()
    for item in data.get("tools", []):
        function_name = item.get("func_name")
        handler = getattr(legacy, function_name, None)
        if handler is None:
            continue
        name = item.get("name", function_name)
        permission = _permission_for(name)
        registry.register(
            ToolSpec(name=name, description=item.get("description", ""), parameters=_signature_schema(handler), permission=permission),
            handler,
        )
    return registry


def _permission_for(name: str) -> ToolPermission:
    if name in {"read_file", "list_directory", "grep_search", "git_status", "git_diff"}:
        return ToolPermission.READ
    if name in {"write_file", "edit_file"}:
        return ToolPermission.WRITE
    if name.startswith("git_"):
        return ToolPermission.GIT
    if name in {"fetch_url", "google_search"}:
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
