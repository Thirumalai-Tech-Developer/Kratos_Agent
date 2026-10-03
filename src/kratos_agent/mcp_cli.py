"""Manage workspace MCP connections without starting the agent runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from kratos_agent.core.mcp_runtime import McpManager


def main(argv: list[str] | None = None, *, announce_reconnect: bool = True) -> int:
    parser = argparse.ArgumentParser(prog="kratos mcp", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("add", "configure", "import", "list", "check", "enable", "disable", "remove"):
        command = commands.add_parser(action)
        command.add_argument("--workspace", type=Path, default=Path.cwd())
        if action == "add":
            command.add_argument("url", help="Remote HTTP MCP endpoint")
            command.add_argument("--name", required=True)
            command.add_argument("--transport", choices=("streamable-http", "sse"), default="streamable-http")
            command.add_argument("--disabled", action="store_true")
            command.add_argument("--replace", action="store_true")
        elif action == "configure":
            command.add_argument("name")
            command.add_argument("file", type=Path, help="JSON containing one server configuration")
        elif action == "import":
            command.add_argument("path", type=Path)
        elif action != "list":
            command.add_argument("name")
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    load_dotenv(workspace / ".env", override=False)
    try:
        manager = McpManager(workspace / ".kratos" / "mcp.json", workspace)
        if args.action == "add":
            url = urlsplit(args.url)
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                raise ValueError("Use an HTTP(S) URL without embedded credentials")
            if args.name in manager.servers and not args.replace:
                raise ValueError("That name already exists; use --replace to update it")
            manager.configure(args.name, {"url": args.url, "type": args.transport, "enabled": not args.disabled})
        elif args.action == "configure":
            manager.configure(args.name, json.loads(args.file.read_text(encoding="utf-8")))
        elif args.action == "import":
            manager.add_import(args.path)
        elif args.action == "list":
            overview = manager.overview()
            for server in overview:
                server["status"] = {"state": "not_checked" if server["enabled"] else "disabled"}
            print(json.dumps(overview, indent=2))
            return 0
        elif args.action == "check":
            server = manager.servers.get(args.name)
            if server is None:
                raise ValueError("MCP server not found")
            if not server.enabled:
                raise ValueError("Enable the connection before checking it")
            try:
                tools = manager._sync_sdk(server, "list_tools")
            except Exception as exc:
                # SDK exceptions can contain headers, command args or tokens.
                print(json.dumps({"name": args.name, "state": "error", "error": type(exc).__name__}))
                return 1
            print(json.dumps({"name": args.name, "state": "connected", "tools": len(tools)}))
            return 0
        elif args.action == "remove":
            manager.remove(args.name)
        else:
            manager.set_enabled(args.name, args.action == "enable")
        print(f"Saved MCP configuration: {manager.config_path}")
        if announce_reconnect:
            print("Use Reconnect on the MCP connections page, or restart Kratos, to apply it.")
        return 0
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(2, f"MCP configuration failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
