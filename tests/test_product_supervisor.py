import os
import socket
import sys
from argparse import Namespace

import pytest

from kratos_agent import product
from kratos_agent.product import ManagedService, http_ready, port_available


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_supervisor_starts_checks_and_stops_owned_service(tmp_path):
    port = free_port()
    service = ManagedService("test-http", [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], tmp_path, dict(os.environ), tmp_path / "service.log")
    try:
        service.start()
        service.wait_ready(f"http://127.0.0.1:{port}/", timeout=10)
        assert http_ready(f"http://127.0.0.1:{port}/")
        assert not port_available(port)
    finally:
        service.stop()
    assert service.process.poll() is not None
    assert port_available(port)


def test_supervisor_reports_child_exit_without_waiting_full_deadline(tmp_path):
    service = ManagedService("failed", [sys.executable, "-c", "raise SystemExit(3)"], tmp_path, dict(os.environ), tmp_path / "failed.log")
    try:
        service.start()
        with pytest.raises(RuntimeError, match="exited before readiness"):
            service.wait_ready(f"http://127.0.0.1:{free_port()}/", timeout=10)
    finally:
        service.stop()


def test_cli_startup_timeout_default_and_override(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(product, "run", captured.append)

    product.main(["run", "--cli", "--workspace", str(tmp_path)])
    product.main(["run", "--cli", "--workspace", str(tmp_path), "--startup-timeout", "30"])

    assert captured[0].startup_timeout == 600
    assert captured[1].startup_timeout == 30


@pytest.mark.parametrize("dev,override,expected", [(True, None, ".build/kratos-dev"), (True, ".build/custom", ".build/custom"), (False, None, None)])
def test_studio_development_cache_is_separate_from_production(monkeypatch, tmp_path, dev, override, expected):
    gateway = tmp_path / "gateway"
    (gateway / "node_modules/next").mkdir(parents=True)
    standalone = gateway / ".build/next/standalone"
    standalone.mkdir(parents=True)
    (standalone / "server-ws.mjs").write_text("")
    monkeypatch.setattr(product, "GATEWAY", gateway)
    monkeypatch.setattr(product.shutil, "which", lambda name: "test-node")
    env = {"NEXT_DIST_DIR": override} if override else {}
    service = product.gateway_service(Namespace(workspace=tmp_path, dev=dev), env)
    assert service.env.get("NEXT_DIST_DIR") == expected
    assert env == ({"NEXT_DIST_DIR": override} if override else {})
    assert service.cwd == (gateway if dev else standalone)
