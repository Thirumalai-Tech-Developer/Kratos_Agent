"""Public high-level API for running the Kratos agent in an application."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from kratos_agent.brain.config import get_default_model
from kratos_agent.core.runtime_contracts import ToolPermission, ToolSpec


class KratosAgent:
    """A first-party agent facade over the Kratos runtime and Kratos model SDK.

    The application runtime is loaded lazily when an agent is instantiated. A
    caller may inject an existing runtime to share sessions and registered tools.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        workspace: str | Path | None = None,
        runtime: Any | None = None,
    ) -> None:
        configured = get_default_model()
        if model and configured and model != configured:
            raise ValueError(f"Kratos is locked to KRATOS_MODEL='{configured}'.")
        self.model = model or configured
        if runtime is None:
            from kratos_agent.main import KratosRuntime
            runtime = KratosRuntime(model_name=self.model, workspace=Path(workspace) if workspace else None)
        self.runtime = runtime

    def run(self, prompt: str) -> str:
        """Run an autonomous task with the application's tools and evidence gates."""
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        return self.runtime.run_agent(prompt)

    def run_chat(self, prompt: str) -> str:
        """Answer without enabling autonomous tool execution."""
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        return self.runtime.run_chat_restricted(prompt)

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
        *,
        permission: ToolPermission = ToolPermission.READ,
        timeout_seconds: int = 300,
    ) -> ToolSpec:
        """Register a JSON-schema tool in the same guarded runtime registry."""
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            permission=permission,
            timeout_seconds=timeout_seconds,
            source="kratos-sdk",
        )
        self.runtime.tools_registry.register(spec, handler)
        self.runtime.tools = self.runtime.tools_registry.specs()
        self.runtime.loop.tools = self.runtime.tools_registry
        return spec
