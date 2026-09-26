"""Tools Plugin - Tool registry bridge and dynamic filtering according to preset."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..plugin import HarnessPlugin, PluginMetadata

if TYPE_CHECKING:
    from ..kernel import HarnessKernel

logger = logging.getLogger(__name__)


class ToolsPlugin(HarnessPlugin):
    """Bridges the tool execution runtime and enforces preset permissions."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(
            metadata=PluginMetadata(
                name="tools",
                version="1.0.0",
                description="Manages tool availability, permissions, and execution filtering.",
                category="tool",
                required_services=[],
                provides_services=["tools"],
            ),
            config=config,
        )
        self._custom_tool_registry: dict[str, Any] = {}

    def on_register(self) -> None:
        """Called when tools plugin is registered."""
        pass

    def on_start(self) -> None:
        """Called when tools plugin starts."""
        pass

    def on_stop(self) -> None:
        """Called when tools plugin stops."""
        pass

    def on_error(self, exc: Exception) -> None:
        """Called when an error occurs in the tools plugin."""
        super().on_error(exc)

    def on_load(self, kernel: HarnessKernel) -> None:
        super().on_load(kernel)
        kernel.register_service("tools", self)

    def on_unload(self) -> None:
        if self.kernel:
            self.kernel.unregister_service("tools")
        super().on_unload()

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is permitted under current kernel preset."""
        if not self.kernel:
            return True
        allowed = self.kernel.get_allowed_tools()
        if allowed is None:
            return True
        return tool_name in allowed

    def filter_tool_definitions(self, tool_defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter standard tool definitions based on active preset."""
        if not self.kernel:
            return tool_defs

        allowed = self.kernel.get_allowed_tools()
        if allowed is None:
            return tool_defs

        filtered = []
        for tool in tool_defs:
            name = None
            if "name" in tool:
                name = tool["name"]
            elif "function" in tool and "name" in tool["function"]:
                name = tool["function"]["name"]

            if name and name in allowed:
                filtered.append(tool)
        return filtered

    def register_custom_tool(self, name: str, callable_handler: Any, schema: dict[str, Any]) -> None:
        """Register a dynamic tool created at runtime."""
        self._custom_tool_registry[name] = {
            "handler": callable_handler,
            "schema": schema,
        }
        if self.kernel:
            self.kernel.emit("custom_tool_registered", name=name)

    def get_custom_tools(self) -> dict[str, Any]:
        return dict(self._custom_tool_registry)
