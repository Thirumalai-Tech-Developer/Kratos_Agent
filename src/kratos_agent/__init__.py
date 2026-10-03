"""Kratos Agent package with lazy application entry points.

Importing a library module (for example ``kratos_agent.sdk``) must not start
the desktop runtime or launch configured MCP servers.
"""
from __future__ import annotations

from typing import Any


def main() -> Any:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from kratos_agent.mcp_cli import main as mcp_main
        return mcp_main(sys.argv[2:])
    cli_flags = {"--cli", "-c", "cli", "/cli"}
    if any(arg in cli_flags for arg in sys.argv[1:]):
        from kratos_agent.product import main as studio_main
        return studio_main(["cli", *(arg for arg in sys.argv[1:] if arg not in cli_flags)])
    if sys.argv[1:] and sys.argv[1] in {"--help", "-h", "help", "/help"}:
        print("Kratos Agent\n\n"
              "  kratos --cli [--workspace PATH] [--port PORT] [--dev]\n"
              "      Run the integrated terminal agent and local model gateway.\n"
              "  kratos mcp --help\n"
              "      Manage workspace MCP connections.\n"
              "  kratos-studio setup --cli\n"
              "      Prepare the gateway for terminal use.\n"
              "  kratos-studio run [--workspace PATH]\n"
              "      Run the Studio web interface.\n\n"
              "Inside the terminal agent, use /help for agent commands.")
        return
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
