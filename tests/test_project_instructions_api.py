"""Project instruction editor uses the authenticated, idle workspace boundary."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from kratos_agent.core.project_memory import ProjectMemory
from kratos_agent.web.server import KratosServer, KratosWebHandler


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_INTERNAL_TOKEN", "project-instruction-test-token")
    project = ProjectMemory(str(tmp_path))
    runtime = SimpleNamespace(workspace=tmp_path, project_memory=project,
        project_instruction_status=project.status, _turn_lock=threading.RLock())
    server = KratosServer(("127.0.0.1", 0), KratosWebHandler, Mock(), Mock(), runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(3)


def call(server, payload=None, *, method=None, token="project-instruction-test-token"):
    request = Request(f"http://127.0.0.1:{server.server_port}/api/project/instructions",
        data=json.dumps(payload).encode() if method == "POST" or payload is not None else None,
        method=method,
        headers={"Content-Type":"application/json", "X-Kratos-Internal-Token":token})
    with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
        return json.load(response)


def test_editor_reads_without_creating_file_and_saves_real_markdown(server):
    initial = call(server)
    assert not initial["exists"]
    assert not (server.runtime.workspace / "kratos.md").exists()
    text = "# Project\nUse the existing build commands.\n"
    saved = call(server, {"content":text, "expected_digest":initial["digest"]})
    assert saved["content"] == text and saved["exists"]
    assert (server.runtime.workspace / "kratos.md").read_text(encoding="utf8") == text
    assert "next message" in saved["message"]
    assert call(server)["digest"] == saved["digest"]


def test_editor_rejects_stale_revision_without_overwriting_user_edits(server):
    saved = call(server, {"content":"# First"})
    (server.runtime.workspace / "kratos.md").write_text("# Edited elsewhere", encoding="utf8")
    with pytest.raises(HTTPError) as exc:
        call(server, {"content":"# Old editor", "expected_digest":saved["digest"]})
    assert exc.value.code == 409
    assert call(server)["content"] == "# Edited elsewhere"


@pytest.mark.parametrize("payload", [
    None, [], {}, {"content":True}, {"content":"hello","path":"outside.md"},
    {"content":"hello","expected_digest":False}, {"content":"a" * 65537},
])
def test_editor_rejects_invalid_or_oversized_instruction_payload(server, payload):
    with pytest.raises(HTTPError) as exc:
        call(server, payload, method="POST")
    assert exc.value.code == 400
    assert not (server.runtime.workspace / "kratos.md").exists()


@pytest.mark.parametrize("lock_name", ["turn_lock", "_turn_lock"])
def test_editor_requires_idle_turn_but_read_remains_available(server, lock_name):
    lock = server.turn_lock if lock_name == "turn_lock" else server.runtime._turn_lock
    lock.acquire()
    try:
        assert not call(server)["exists"]
        with pytest.raises(HTTPError) as exc:
            call(server, {"content":"# Busy"})
        assert exc.value.code == 409
    finally:
        lock.release()
    assert not (server.runtime.workspace / "kratos.md").exists()


def test_editor_is_authenticated(server):
    with pytest.raises(HTTPError) as exc:
        call(server, token="")
    assert exc.value.code == 401


def test_editor_cannot_overwrite_a_file_created_after_its_initial_read(server):
    initial = call(server)
    assert not initial["exists"] and initial["digest"] is None
    path = server.runtime.workspace / "kratos.md"
    path.write_text("# New user instructions", encoding="utf8")
    with pytest.raises(HTTPError) as exc:
        call(server, {"content":"# Stale new-file editor", "expected_digest":initial["digest"]})
    assert exc.value.code == 409
    assert path.read_text(encoding="utf8") == "# New user instructions"
