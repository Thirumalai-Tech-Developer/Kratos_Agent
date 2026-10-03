import json

import pytest

from kratos_agent.core.mcp_runtime import McpManager


def manager(tmp_path):
    return McpManager(tmp_path / ".kratos" / "mcp.json", tmp_path)


def test_configuration_update_toggle_and_removal_survive_reload(tmp_path):
    mcp = manager(tmp_path)
    mcp.configure("test-server", {"command": "test-command", "args": ["--version"], "enabled": False})
    mcp.load()
    assert mcp.servers["test-server"].args == ["--version"]
    mcp.configure("test-server", {"url": "https://example.com/mcp", "enabled": False})
    mcp.set_enabled("test-server", True)
    mcp.load()
    assert mcp.servers["test-server"].enabled
    assert mcp.servers["test-server"].command is None
    mcp.remove("test-server")
    mcp.load()
    assert "test-server" not in mcp.servers


def test_remove_imported_server_does_not_reappear_or_edit_external_config(tmp_path):
    source = tmp_path / "external.json"
    data = {"mcpServers": {"imported": {"command": "test-command", "enabled": False}}}
    source.write_text(json.dumps(data))
    mcp = manager(tmp_path)
    mcp.add_import(source)
    mcp.remove("imported")
    mcp.load()
    assert "imported" not in mcp.servers
    assert json.loads(source.read_text()) == data


def test_namespace_collision_rejected_before_save(tmp_path):
    mcp = manager(tmp_path)
    mcp.configure("a.b", {"command": "test-command", "enabled": False})
    with pytest.raises(ValueError, match="collides"):
        mcp.configure("a_b", {"command": "test-command", "enabled": False})


def test_overview_excludes_credentials_and_command_arguments(tmp_path):
    mcp = manager(tmp_path)
    mcp.configure("private", {"command": "test-command", "args": ["secret-argument"], "env": {"API_KEY": "secret-value"}, "headers": {"Authorization": "secret-token"}, "enabled": False})
    overview = json.dumps(mcp.overview())
    for secret in ["secret-argument", "secret-value", "secret-token"]:
        assert secret not in overview
    assert "API_KEY" in overview
