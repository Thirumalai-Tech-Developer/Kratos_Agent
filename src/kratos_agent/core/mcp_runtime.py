"""MCP client bridge for Claude Code, OpenClaw, and standard MCP configs.

Kratos uses the upstream MCP SDK for protocol and transport handling. External
framework configs are not auto-scanned. Users explicitly import a config (or
edit Kratos's own `.kratos/mcp.json`), after which enabled servers connect at
startup.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runtime_contracts import ToolPermission, ToolSpec


@dataclass
class McpServerConfig:
    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    transport: str | None = None
    cwd: str | None = None
    enabled: bool = True
    timeout_seconds: int = 30

    @classmethod
    def from_mapping(cls, name: str, raw: Mapping[str, Any]) -> McpServerConfig:
        if not isinstance(raw, Mapping):
            raise ValueError("server entry must be a JSON object")
        command = raw.get("command")
        url = raw.get("url")
        transport = str(raw.get("type", raw.get("transport", "")) or "").lower() or None
        if transport == "http":
            transport = "streamable-http"
        if url and transport is None:
            transport = "streamable-http"
        if bool(command) == bool(url):
            raise ValueError("provide exactly one of command or url")
        if transport not in (None, "stdio", "streamable-http", "sse"):
            raise ValueError(f"unsupported MCP transport: {transport}")
        if url and transport == "stdio":
            raise ValueError("stdio transport requires a command")
        if command and transport not in (None, "stdio"):
            raise ValueError("HTTP/SSE transport requires a URL")
        args = raw.get("args", [])
        env = raw.get("env", {})
        headers = raw.get("headers", {})
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ValueError("args must be an array of strings")
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ValueError("env must be an object of string values")
        if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
            raise ValueError("headers must be an object of string values")
        if command and not isinstance(command, str):
            raise ValueError("command must be a string")
        if url and not isinstance(url, str):
            raise ValueError("url must be a string")
        return cls(
            name=name,
            command=command,
            args=list(args),
            url=url,
            env=dict(env),
            headers=dict(headers),
            transport=transport,
            cwd=str(raw["cwd"]) if raw.get("cwd") else None,
            enabled=raw.get("enabled", True) is not False,
            timeout_seconds=max(1, min(int(raw.get("timeout", raw.get("timeout_seconds", 30))), 300)),
        )


def _expand_env(value: str) -> str:
    """Expand Claude-style ${NAME} and ${NAME:-default} references at use time."""
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        resolved = os.environ.get(name)
        if resolved is None:
            if default is not None:
                return default
            raise ValueError(f"required environment variable {name} is not set")
        return resolved

    return pattern.sub(replace, value)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    if not cleaned:
        raise ValueError("MCP server and tool names must contain letters or numbers")
    return cleaned[:80]


class McpManager:
    """Loads MCP configs, connects with the official SDK, and registers tools."""

    def __init__(self, config_path: Path, workspace: Path | None = None) -> None:
        self.config_path = config_path.resolve()
        self.workspace = (workspace or self.config_path.parent.parent).resolve()
        self.servers: dict[str, McpServerConfig] = {}
        self.import_paths: list[Path] = []
        self._local_names: set[str] = set()
        self.status: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        """Load local config and explicitly imported Claude/OpenClaw config files."""
        self.servers = {}
        self.import_paths = []
        self._local_names = set()
        self.status = {}
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Cannot read MCP config {self.config_path}: {type(exc).__name__}") from exc
            raw_imports = data.get("imports", [])
            if isinstance(raw_imports, list):
                self.import_paths = [Path(item).expanduser().resolve() for item in raw_imports if isinstance(item, str)]
            for path in self.import_paths:
                self._load_external_file(path)
            local_servers = self._extract_servers(data)
            self._merge_server_map(local_servers)
            self._local_names = set(local_servers)

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"imports": [str(path) for path in self.import_paths], "mcpServers": {}}
        for name, server in self.servers.items():
            if name not in self._local_names:
                continue
            raw = {
                "enabled": server.enabled,
                "args": server.args,
                "env": server.env,
                "headers": server.headers,
                "type": server.transport,
                "timeout": server.timeout_seconds,
            }
            for key in ("command", "url", "cwd"):
                value = getattr(server, key)
                if value is not None:
                    raw[key] = value
            data["mcpServers"][name] = raw
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _extract_servers(data: Mapping[str, Any], project: str | None = None) -> Mapping[str, Any]:
        """Read common MCP locations used by MCP, Claude Code, and OpenClaw."""
        servers = data.get("mcpServers")
        if isinstance(servers, dict):
            return servers
        mcp = data.get("mcp")
        if isinstance(mcp, dict) and isinstance(mcp.get("servers"), dict):
            return mcp["servers"]
        if project:
            projects = data.get("projects")
            if isinstance(projects, dict):
                project_data = projects.get(project)
                if isinstance(project_data, dict) and isinstance(project_data.get("mcpServers"), dict):
                    return project_data["mcpServers"]
        return {}

    def _merge_server_map(self, servers: Mapping[str, Any]) -> None:
        for name, raw in servers.items():
            if not isinstance(name, str):
                continue
            try:
                self.servers[name] = McpServerConfig.from_mapping(name, raw)
            except (TypeError, ValueError, OverflowError) as exc:
                self.status[name] = {"state": "invalid", "error": str(exc)}

    def _load_external_file(self, path: Path) -> None:
        if not path.is_file():
            self.status[str(path)] = {"state": "missing", "error": "imported config file not found"}
            return
        try:
            raw = path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # OpenClaw stores its main config as JSON5; Claude's .mcp.json
                # and ~/.claude.json remain ordinary JSON.
                import json5
                data = json5.loads(raw)
        except (OSError, ValueError) as exc:
            self.status[str(path)] = {"state": "invalid", "error": type(exc).__name__}
            return
        servers = dict(self._extract_servers(data))
        # Claude Code stores project-scoped MCP entries in ~/.claude.json.
        projects = data.get("projects")
        project_data = projects.get(str(self.workspace), {}) if isinstance(projects, dict) else {}
        if isinstance(project_data, dict) and isinstance(project_data.get("mcpServers"), dict):
            servers.update(project_data["mcpServers"])
        if path.name in {"mcp.json", ".mcp.json"} and path.parent.is_dir():
            plugin_root = str(path.parent)
            plugin_data = str(self.workspace / ".kratos" / "plugin-data" / path.parent.name)
            servers = {
                name: self._replace_plugin_placeholders(raw, plugin_root, plugin_data)
                for name, raw in servers.items()
            }
        self._merge_server_map(servers)

    @classmethod
    def _replace_plugin_placeholders(cls, value: Any, plugin_root: str, plugin_data: str) -> Any:
        if isinstance(value, str):
            replaced = value.replace("${PLUGIN_ROOT}", plugin_root).replace("${PLUGIN_DATA}", plugin_data)
            if replaced != value:
                return os.path.normpath(replaced)
            return value
        if isinstance(value, list):
            return [cls._replace_plugin_placeholders(item, plugin_root, plugin_data) for item in value]
        if isinstance(value, dict):
            result = {key: cls._replace_plugin_placeholders(item, plugin_root, plugin_data) for key, item in value.items()}
            if "command" in result and "cwd" not in result:
                result["cwd"] = plugin_root
            return result
        return value

    def add_import(self, config_path: Path | str) -> int:
        """Persist a reference to an existing framework config; do not copy secrets."""
        path = Path(config_path).expanduser().resolve()
        if path.is_dir():
            candidates = [path / ".mcp.json", path / "mcp.json"]
            path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
        if path not in self.import_paths:
            self.import_paths.append(path)
            self.save()
        self.load()
        return len(self.servers)

    def import_framework_config(self, framework: str) -> int:
        name = framework.lower()
        if name in ("claude", "claude-code", "claude_code"):
            candidates = [
                self.workspace / ".mcp.json",
                Path.home() / ".claude.json",
            ]
        elif name in ("openclaw", "open-claw"):
            candidates = [Path.home() / ".openclaw" / "openclaw.json"]
        else:
            return self.add_import(framework)
        existing = next((path for path in candidates if path.is_file()), None)
        if existing is None:
            raise FileNotFoundError(f"No {framework} MCP config was found in its standard location")
        return self.add_import(existing)

    def discover(self, server_name: str, discoverer: Callable[[McpServerConfig], list[tuple[ToolSpec, Callable[..., str]]]], registry: Any) -> int:
        """Register discovered tools under stable MCP namespaced tool ids."""
        server = self.servers.get(server_name)
        if not server or not server.enabled:
            return 0
        discovered = discoverer(server)
        for spec, handler in discovered:
            prefix = f"mcp__{_safe_name(server_name)}__"
            name = spec.name if spec.name.startswith(prefix) else prefix + _safe_name(spec.name)
            registered = ToolSpec(name, spec.description, spec.parameters, spec.permission, spec.timeout_seconds, source=f"mcp:{server_name}")
            registry.register(registered, handler)
        return len(discovered)

    def discover_enabled(self, registry: Any) -> dict[str, dict[str, Any]]:
        """Connect to each enabled server independently; failures do not abort startup."""
        summary: dict[str, dict[str, Any]] = {}
        for name, server in list(self.servers.items()):
            if not server.enabled:
                self.status[name] = {"state": "disabled", "tools": 0}
                continue
            try:
                count = self.discover(name, self._discover_sdk, registry)
                self.status[name] = {"state": "connected", "tools": count, "transport": server.transport or ("stdio" if server.command else "streamable-http")}
            except Exception as exc:  # External server failures must not prevent Kratos startup.
                self.status[name] = {"state": "error", "tools": 0, "error": type(exc).__name__}
            summary[name] = dict(self.status[name])
        return summary

    def _sync_sdk(self, server: McpServerConfig, operation: str, tool_name: str | None = None, arguments: dict[str, Any] | None = None) -> Any:
        async def run() -> Any:
            async with self._client(server) as client:
                if operation == "list_tools":
                    result = await client.list_tools()
                    return list(result.tools)
                if operation in {"list_resources", "list_prompts"}:
                    result = await getattr(client, operation)()
                    field = "resources" if operation == "list_resources" else "prompts"
                    return list(getattr(result, field, []) or [])
                if operation == "read_resource":
                    result = await client.read_resource(str((arguments or {}).get("uri", "")))
                    return self._format_result(result)
                if operation == "get_prompt":
                    result = await client.get_prompt(str((arguments or {}).get("name", "")), (arguments or {}).get("arguments", {}))
                    return self._format_result(result)
                result = await client.call_tool(tool_name or "", arguments or {})
                if getattr(result, "is_error", False):
                    raise RuntimeError(self._format_result(result))
                return self._format_result(result)

        from kratos_agent.utils.async_runner import run_coroutine
        return run_coroutine(run())

    @asynccontextmanager
    async def _client(self, server: McpServerConfig):
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as exc:
            raise RuntimeError("Install Kratos with `uv sync` to enable MCP support") from exc

        timeout = float(server.timeout_seconds)
        if server.command:
            params = StdioServerParameters(
                command=_expand_env(server.command),
                args=[_expand_env(value) for value in server.args],
                env={key: _expand_env(value) for key, value in server.env.items()},
                cwd=_expand_env(server.cwd) if server.cwd else None,
            )
            async with Client(params, read_timeout_seconds=timeout) as client:
                yield client
            return

        if not server.url:
            raise ValueError("MCP server requires a command or URL")
        url = _expand_env(server.url)
        headers = {key: _expand_env(value) for key, value in server.headers.items()}
        if server.transport == "sse":
            from mcp.client.sse import sse_client
            async with Client(sse_client(url, headers=headers, timeout=timeout, sse_read_timeout=timeout), read_timeout_seconds=timeout) as client:
                yield client
            return

        if headers:
            import httpx2
            from mcp.client.streamable_http import streamable_http_client
            async with httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(timeout, read=timeout)) as http_client:
                async with Client(streamable_http_client(url, http_client=http_client), read_timeout_seconds=timeout) as client:
                    yield client
            return

        async with Client(url, read_timeout_seconds=timeout) as client:
            yield client

    @staticmethod
    def _format_result(result: Any) -> str:
        payload: dict[str, Any] = {}
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            payload["structuredContent"] = structured
        blocks = []
        source_blocks = (
            getattr(result, "content", None)
            or getattr(result, "contents", None)
            or getattr(result, "messages", None)
            or []
        )
        for block in source_blocks:
            if hasattr(block, "model_dump"):
                blocks.append(block.model_dump(mode="json", by_alias=True))
                continue
            text = getattr(block, "text", None)
            if text is not None:
                blocks.append({"type": "text", "text": text})
            else:
                blocks.append({"type": type(block).__name__, "data": str(block)[:1000]})
        if blocks:
            payload["content"] = blocks
        if not payload:
            payload["content"] = []
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _discover_sdk(self, server: McpServerConfig) -> list[tuple[ToolSpec, Callable[..., str]]]:
        discovered = []
        for tool in self._sync_sdk(server, "list_tools"):
            annotations = getattr(tool, "annotations", None)
            if isinstance(annotations, Mapping):
                read_only = annotations.get("readOnlyHint", annotations.get("read_only_hint")) is True
            else:
                read_only = getattr(annotations, "readOnlyHint", getattr(annotations, "read_only_hint", False)) is True
            permission = ToolPermission.READ if read_only else ToolPermission.EXECUTE
            raw_schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
            if not isinstance(raw_schema, dict):
                raw_schema = {"type": "object", "properties": {}}
            spec = ToolSpec(
                name=f"mcp__{_safe_name(server.name)}__{_safe_name(tool.name)}",
                description=str(getattr(tool, "description", "") or f"MCP tool {tool.name} from {server.name}"),
                parameters=raw_schema,
                permission=permission,
                timeout_seconds=server.timeout_seconds,
                source=f"mcp:{server.name}",
            )
            original_name = tool.name
            handler = lambda _tool_name=original_name, **kwargs: self._sync_sdk(server, "call_tool", _tool_name, kwargs)
            discovered.append((spec, handler))
        for operation, tool_name, read_operation, read_name, description, read_description, argument_name, argument_schema in (
            ("list_resources", "resources_list", "read_resource", "resource_read", "List data resources exposed by this MCP server.", "Read an MCP resource by URI.", "uri", {"type": "string"}),
            ("list_prompts", "prompts_list", "get_prompt", "prompt_get", "List prompt templates exposed by this MCP server.", "Render a prompt template exposed by this MCP server.", "name", {"type": "string"}),
        ):
            try:
                available_items = self._sync_sdk(server, operation)
            except Exception:
                continue  # Servers are allowed to implement tools without prompts/resources.
            list_spec = ToolSpec(
                name=f"mcp__{_safe_name(server.name)}__{tool_name}",
                description=description,
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                permission=ToolPermission.READ,
                timeout_seconds=server.timeout_seconds,
                source=f"mcp:{server.name}",
            )
            discovered.append((list_spec, lambda _operation=operation, **kwargs: self._sync_sdk(server, _operation, arguments=kwargs)))
            if available_items:
                properties = {argument_name: argument_schema}
                if read_operation == "get_prompt":
                    properties["arguments"] = {"type": "object", "additionalProperties": {"type": "string"}}
                read_spec = ToolSpec(
                    name=f"mcp__{_safe_name(server.name)}__{read_name}",
                    description=read_description,
                    parameters={"type": "object", "properties": properties, "required": [argument_name], "additionalProperties": False},
                    permission=ToolPermission.READ,
                    timeout_seconds=server.timeout_seconds,
                    source=f"mcp:{server.name}",
                )
                discovered.append((read_spec, lambda _operation=read_operation, **kwargs: self._sync_sdk(server, _operation, arguments=kwargs)))
        return discovered
