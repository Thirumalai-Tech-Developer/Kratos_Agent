import json
import sys
from pathlib import Path
from kratos_agent.core.mcp_runtime import McpManager
from kratos_agent.core.runtime_contracts import ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import ToolRegistry


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_mcp_stdio_server_discovery_and_tool_call(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_COMPUTER_USE_MCP", "false")
    monkeypatch.setenv("KRATOS_OPENPETS_MCP", "false")
    server_file = tmp_path / "mcp_server.py"
    server_file.write_text(
        "from mcp.server import MCPServer\n"
        "from mcp.types import ToolAnnotations\n"
        "server = MCPServer('Smoke MCP')\n"
        "@server.tool(annotations=ToolAnnotations(readOnlyHint=True))\n"
        "def echo(value: str) -> str:\n"
        "    return 'echo:' + value\n"
        "if __name__ == '__main__':\n"
        "    server.run('stdio')\n",
        encoding="utf-8",
    )
    config_path = tmp_path / ".kratos" / "mcp.json"
    write_json(config_path, {"mcpServers": {"smoke": {"command": sys.executable, "args": ["-u", str(server_file)]}}})
    manager = McpManager(config_path, tmp_path)
    registry = ToolRegistry()

    status = manager.discover_enabled(registry)

    assert status["smoke"]["state"] == "connected"
    assert status["smoke"]["tools"] >= 1
    spec = next(spec for spec in registry.specs() if spec.name == "mcp__smoke__echo")
    assert spec.permission is ToolPermission.READ
    result = registry.execute(ToolCall(spec.name, {"value": "hello"}), lambda spec, args: (True, "test"))
    assert not result.is_error
    assert "echo:hello" in result.content


def test_importing_user_mcp_config_references_file_without_copying_secrets(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_path = tmp_path / ".claude.json"
    write_json(config_path, {"mcpServers": {"private": {"command": "server", "env": {"API_KEY": "secret-value"}}}})
    manager = McpManager(workspace / ".kratos" / "mcp.json", workspace)

    manager.add_import(config_path)

    assert "private" in manager.servers
    local_config = json.loads((workspace / ".kratos" / "mcp.json").read_text(encoding="utf-8"))
    assert local_config["imports"] == [str(config_path.resolve())]
    assert "secret-value" not in json.dumps(local_config)
    assert "private" not in local_config["mcpServers"]


def test_user_selected_json5_mcp_config_is_imported(tmp_path):
    config_path = tmp_path / "mcp-config.json5"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "{ // JSON5 MCP configuration\n mcp: { servers: { docs: { type: 'http', url: 'https://example.invalid/mcp' } } } }",
        encoding="utf-8",
    )
    manager = McpManager(tmp_path / ".kratos" / "mcp.json", tmp_path)

    manager.add_import(config_path)

    assert manager.servers["docs"].transport == "streamable-http"
    assert manager.servers["docs"].url == "https://example.invalid/mcp"


def test_openclaw_plugin_placeholders_are_expanded_without_mutating_bundle(tmp_path):
    bundle = tmp_path / "plugin"
    original = {
        "mcpServers": {
            "plugin": {
                "command": sys.executable,
                "args": ["${PLUGIN_ROOT}/server.py", "${PLUGIN_DATA}"],
            }
        }
    }
    write_json(bundle / "mcp.json", original)
    manager = McpManager(tmp_path / ".kratos" / "mcp.json", tmp_path)

    manager.add_import(bundle / "mcp.json")

    server = manager.servers["plugin"]
    assert server.args == [str(bundle / "server.py"), str(tmp_path / ".kratos" / "plugin-data" / "plugin")]
    assert server.cwd == str(bundle)
    assert json.loads((bundle / "mcp.json").read_text(encoding="utf-8")) == original


def test_runtime_discovery_includes_relevant_mcp_tools_not_in_static_index():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "mcp__notion__create_page",
            "Create a page in Notion using the selected parent page.",
            {"type": "object", "properties": {"title": {"type": "string"}}},
            ToolPermission.EXECUTE,
            source="mcp:notion",
        ),
        lambda title: title,
    )

    schemas = registry.schemas(context="Create a project page in Notion")

    assert any(item["function"]["name"] == "mcp__notion__create_page" for item in schemas)
