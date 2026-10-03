import json

import pytest

from kratos_agent.core.mcp_runtime import McpManager
from kratos_agent.mcp_cli import main


def test_cli_lifecycle_persists_without_connecting_servers(tmp_path, monkeypatch, capsys):
    def unexpected_connection(*args):
        pytest.fail("Configuration commands must not start MCP servers")

    monkeypatch.setattr(McpManager, "_sync_sdk", unexpected_connection)
    workspace = ["--workspace", str(tmp_path)]
    assert main(["add", "https://example.com/mcp", "--name", "docs", *workspace]) == 0
    assert main(["disable", "docs", *workspace]) == 0
    manager = McpManager(tmp_path / ".kratos/mcp.json", tmp_path)
    assert manager.servers["docs"].url == "https://example.com/mcp"
    assert not manager.servers["docs"].enabled
    assert main(["enable", "docs", *workspace]) == 0
    assert main(["remove", "docs", *workspace]) == 0
    assert "docs" not in McpManager(tmp_path / ".kratos/mcp.json", tmp_path).servers
    assert "Reconnect" in capsys.readouterr().out


@pytest.mark.parametrize("url", ["file:///secret", "ftp://example.com/mcp", "https://user:secret@example.com/mcp", "https://"])
def test_cli_rejects_invalid_urls_without_writing_config(tmp_path, url):
    with pytest.raises(SystemExit) as error:
        main(["add", url, "--name", "docs", "--workspace", str(tmp_path)])
    assert error.value.code == 2
    assert not (tmp_path / ".kratos/mcp.json").exists()


def test_cli_requires_explicit_replace_for_existing_connection(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["add", "https://example.com/mcp", "--name", "context7", "--workspace", str(tmp_path)])
    assert error.value.code == 2
    assert main(["add", "https://example.com/mcp", "--name", "context7", "--replace", "--workspace", str(tmp_path)]) == 0


def test_cli_checks_only_selected_server_and_redacts_sdk_failure(tmp_path, monkeypatch, capsys):
    manager = McpManager(tmp_path / ".kratos/mcp.json", tmp_path)
    manager.configure("docs", {"url": "https://example.com/mcp"})
    checked = []

    def discover(self, server, operation):
        checked.append((server.name, operation))
        raise RuntimeError("Authorization: secret-token")

    monkeypatch.setattr(McpManager, "_sync_sdk", discover)
    assert main(["check", "docs", "--workspace", str(tmp_path)]) == 1
    assert checked == [("docs", "list_tools")]
    output = capsys.readouterr().out
    assert "secret-token" not in output
    assert json.loads(output)["error"] == "RuntimeError"


def test_configure_and_import_support_local_plugin_configs(tmp_path):
    config = tmp_path / "server.json"
    config.write_text(json.dumps({"command": "test-command", "args": ["--stdio"], "enabled": False}))
    assert main(["configure", "local", str(config), "--workspace", str(tmp_path)]) == 0
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"plugin-server": {"command": "test-command", "enabled": False}}}))
    assert main(["import", str(plugin), "--workspace", str(tmp_path)]) == 0
    manager = McpManager(tmp_path / ".kratos/mcp.json", tmp_path)
    assert manager.servers["local"].args == ["--stdio"]
    assert "plugin-server" in manager.servers
