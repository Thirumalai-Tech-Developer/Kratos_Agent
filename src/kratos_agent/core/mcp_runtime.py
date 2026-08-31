"""MCP server configuration and dynamic tool registration boundary.

Transport clients are pluggable: an stdio/SSE client supplies discovered ToolSpec
objects and handlers, while the agent loop treats them exactly like built-in tools.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Dict, List

from .runtime_contracts import ToolPermission, ToolSpec


@dataclass
class McpServerConfig:
    name: str
    command: str | None = None
    args: List[str] | None = None
    url: str | None = None
    env: Dict[str, str] | None = None
    enabled: bool = True


class McpManager:
    """Owns configuration, discovery lifecycle, and namespaced registration."""
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.servers: Dict[str, McpServerConfig] = {}
        self.load()

    def load(self) -> None:
        if not self.config_path.exists():
            return
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        raw = data.get("mcpServers", data.get("servers", {}))
        self.servers = {name: McpServerConfig(name=name, **value) for name, value in raw.items()}

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"mcpServers": {name: {k: v for k, v in vars(server).items() if k != "name" and v is not None} for name, server in self.servers.items()}}
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def discover(self, server_name: str, discoverer: Callable[[McpServerConfig], List[tuple[ToolSpec, Callable[..., str]]]], registry: Any) -> int:
        """Register externally discovered tools as `mcp__server__tool`.

        A failed discovery does not alter existing registrations; callers can retry
        after credentials or a server process recover.
        """
        server = self.servers.get(server_name)
        if not server or not server.enabled:
            return 0
        discovered = discoverer(server)
        for spec, handler in discovered:
            name = spec.name if spec.name.startswith("mcp__") else f"mcp__{server_name}__{spec.name}"
            registry.register(ToolSpec(name, spec.description, spec.parameters, spec.permission, spec.timeout_seconds, source=f"mcp:{server_name}"), handler)
        return len(discovered)
