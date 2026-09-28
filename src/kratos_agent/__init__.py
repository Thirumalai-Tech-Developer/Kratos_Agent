"""Kratos Agent package with lazy application entry points.

Importing a library module (for example ``kratos_agent.sdk``) must not start
the desktop runtime or launch configured MCP servers.
"""
from __future__ import annotations

from typing import Any


def main() -> Any:
    from kratos_agent.main import main as app_main
    return app_main()


def run_agent(query: str) -> str:
    from kratos_agent.main import run_agent as app_run_agent
    return app_run_agent(query)


def reload_tools() -> None:
    from kratos_agent.main import reload_tools as app_reload_tools
    return app_reload_tools()


def set_model(model_name: str) -> None:
    from kratos_agent.main import set_model as app_set_model
    return app_set_model(model_name)


def __getattr__(name: str) -> Any:
    if name == "runtime":
        from kratos_agent.main import runtime
        return runtime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["main", "reload_tools", "run_agent", "runtime", "set_model"]
