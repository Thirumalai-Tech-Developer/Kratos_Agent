import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from kratos_agent.core.mcp_runtime import McpManager, McpServerConfig


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


@pytest.mark.parametrize("delay_at", ["connection", "operation"])
def test_mcp_deadline_covers_connection_and_request(tmp_path, monkeypatch, delay_at):
    mcp = manager(tmp_path)
    closed = []

    async def list_tools():
        if delay_at == "operation":
            await asyncio.sleep(0.1)
        return SimpleNamespace(tools=[])

    @asynccontextmanager
    async def client(server):
        try:
            if delay_at == "connection":
                await asyncio.sleep(0.1)
            yield SimpleNamespace(list_tools=list_tools)
        finally:
            closed.append(True)

    monkeypatch.setattr(mcp, "_client", client)
    server = McpServerConfig(name="slow", command="test-only", timeout_seconds=0.01)
    with pytest.raises(TimeoutError):
        mcp._sync_sdk(server, "list_tools")
    assert closed == [True]
