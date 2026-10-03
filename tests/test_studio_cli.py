"""Studio terminal launcher lifecycle and configuration integration."""
import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from kratos_agent import product


def arguments(workspace, **overrides):
    values = dict(workspace=workspace, data_dir=None, port=20228, agent_port=7860,
                  dev=False, cli=True, no_browser=False, startup_timeout=20)
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def cli_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(product, "ROOT", tmp_path / "application")
    monkeypatch.setattr(product, "GATEWAY", tmp_path / "application/services/omniroute")
    monkeypatch.setenv("KRATOS_MODEL", "test/model")
    monkeypatch.setenv("KRATOS_BROWSER_SESSION_SYNC", "false")
    monkeypatch.setattr(product, "gateway_models", lambda env: ["test/model"])
    return arguments(tmp_path / "workspace")


def test_reuses_ready_gateway_without_starting_or_stopping_it(cli_environment, monkeypatch):
    owned_service = MagicMock()
    terminal = MagicMock()
    monkeypatch.setattr(product, "port_available", lambda port: False)
    monkeypatch.setattr(product, "http_ready", lambda *args: True)
    monkeypatch.setattr(product, "gateway_service", owned_service)
    monkeypatch.setattr(product, "launch_terminal", terminal)
    product.run_cli(cli_environment)
    owned_service.assert_not_called()
    workspace, env = terminal.call_args.args
    assert workspace == cli_environment.workspace.resolve()
    assert env["KRATOS_BASE_URL"] == "http://127.0.0.1:20228/v1"
    assert env["KRATOS_MODEL_ENDPOINT"] == "http://127.0.0.1:20228/v1/models"


@pytest.mark.parametrize("terminal_error", [False, True])
def test_owned_gateway_is_stopped_on_exit_and_terminal_error(cli_environment, monkeypatch, terminal_error):
    service = MagicMock()
    terminal = MagicMock(side_effect=RuntimeError("terminal failed") if terminal_error else None)
    monkeypatch.setattr(product, "port_available", lambda port: True)
    monkeypatch.setattr(product, "gateway_service", lambda *args: service)
    monkeypatch.setattr(product, "launch_terminal", terminal)
    if terminal_error:
        with pytest.raises(RuntimeError, match="terminal failed"):
            product.run_cli(cli_environment)
    else:
        product.run_cli(cli_environment)
    service.start.assert_called_once()
    service.wait_ready.assert_called_once()
    service.stop.assert_called_once()


def test_unhealthy_occupied_port_is_not_adopted(cli_environment, monkeypatch):
    monkeypatch.setattr(product, "port_available", lambda port: False)
    monkeypatch.setattr(product, "http_ready", lambda *args: False)
    terminal = MagicMock()
    monkeypatch.setattr(product, "launch_terminal", terminal)
    with pytest.raises(RuntimeError, match="not ready"):
        product.run_cli(cli_environment)
    terminal.assert_not_called()


@pytest.mark.parametrize("model", ["", "missing/model"])
def test_missing_model_reports_configuration_and_cleans_gateway(cli_environment, monkeypatch, model):
    monkeypatch.setenv("KRATOS_MODEL", model)
    service = MagicMock()
    monkeypatch.setattr(product, "port_available", lambda port: True)
    monkeypatch.setattr(product, "gateway_service", lambda *args: service)
    terminal = MagicMock()
    monkeypatch.setattr(product, "launch_terminal", terminal)
    with pytest.raises(RuntimeError, match="KRATOS_MODEL"):
        product.run_cli(cli_environment)
    terminal.assert_not_called()
    service.stop.assert_called_once()


def test_workspace_settings_override_application_defaults_and_secrets_persist(cli_environment):
    cli_environment.workspace.mkdir()
    (cli_environment.workspace / ".env").write_text("CLI_SETTING=workspace\n", encoding="utf-8")
    product.ROOT.mkdir(parents=True)
    (product.ROOT / ".env").write_text("CLI_SETTING=application\n", encoding="utf-8")
    previous = dict(os.environ)
    try:
        env = product.prepare_environment(cli_environment)
        assert env["CLI_SETTING"] == "workspace"
        assert env["JWT_SECRET"] == product.prepare_environment(cli_environment)["JWT_SECRET"]
        assert env["KRATOS_API_KEY"] == env["OMNIROUTE_API_KEY"]
        assert env["KRATOS_API_KEY"] == product.prepare_environment(cli_environment)["KRATOS_API_KEY"]
    finally:
        os.environ.clear()
        os.environ.update(previous)


def test_terminal_import_sees_selected_workspace_and_env(tmp_path, monkeypatch):
    original_cwd, original_argv = Path.cwd(), sys.argv
    observed = {}
    def main():
        observed.update(cwd=Path.cwd(), endpoint=os.environ["KRATOS_BASE_URL"], argv=sys.argv)
    monkeypatch.setitem(sys.modules, "kratos_agent.cli", SimpleNamespace(main=main))
    monkeypatch.setenv("KRATOS_BASE_URL", "original")
    product.launch_terminal(tmp_path, {"KRATOS_BASE_URL": "http://127.0.0.1:20228/v1"})
    assert observed == dict(cwd=tmp_path, endpoint="http://127.0.0.1:20228/v1", argv=["kratos", "--cli"])
    assert Path.cwd() == original_cwd and sys.argv is original_argv
    assert os.environ["KRATOS_BASE_URL"] == "original"


def test_cli_setup_builds_gateway_without_web_frontend(tmp_path, monkeypatch):
    monkeypatch.setattr(product, "GATEWAY", tmp_path / "gateway")
    dependency = product.GATEWAY / "node_modules/better-sqlite3/package.json"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("{}")
    monkeypatch.setattr(product.shutil, "which", lambda name: "npm")
    execute = MagicMock()
    monkeypatch.setattr(product.subprocess, "run", execute)
    product.setup(arguments(tmp_path))
    assert all(call.kwargs["cwd"] == product.GATEWAY for call in execute.call_args_list)
    assert execute.call_args.args[0] == ["npm", "run", "build"]


@pytest.mark.parametrize("argv", [["run", "--cli"], ["cli"], ["--cli"]])
def test_launcher_cli_aliases(argv, monkeypatch):
    execute = MagicMock()
    monkeypatch.setattr(product, "run", execute)
    product.main(argv)
    assert execute.call_args.args[0].cli is True


def test_original_kratos_cli_uses_integrated_launcher(monkeypatch):
    import kratos_agent
    execute = MagicMock()
    monkeypatch.setattr(product, "main", execute)
    monkeypatch.setattr(sys, "argv", ["kratos", "--cli", "--workspace", "C:/work", "--port", "20228"])
    kratos_agent.main()
    execute.assert_called_once_with(["cli", "--workspace", "C:/work", "--port", "20228"])


def test_model_route_cold_start_is_retried(monkeypatch):
    failure = RuntimeError("cold route")
    failure.__cause__ = TimeoutError("compiling")
    query = MagicMock(side_effect=[failure, ["test/model"]])
    monkeypatch.setattr(product, "gateway_models", query)
    monkeypatch.setattr(product.time, "sleep", lambda duration: None)
    assert product.wait_gateway_models({}, 10) == ["test/model"]
    assert query.call_count == 2


def test_model_route_auth_failure_is_not_retried(monkeypatch):
    from urllib.error import HTTPError
    failure = RuntimeError("invalid key")
    failure.__cause__ = HTTPError("http://localhost/v1/models", 401, "unauthorized", {}, None)
    query = MagicMock(side_effect=failure)
    monkeypatch.setattr(product, "gateway_models", query)
    with pytest.raises(RuntimeError, match="invalid key"):
        product.wait_gateway_models({}, 10)
    query.assert_called_once()


def test_help_does_not_import_agent_runtime(monkeypatch, capsys):
    import kratos_agent
    monkeypatch.setitem(sys.modules, "kratos_agent.main", None)
    monkeypatch.setattr(sys, "argv", ["kratos", "--help"])
    kratos_agent.main()
    assert "kratos --cli" in capsys.readouterr().out
