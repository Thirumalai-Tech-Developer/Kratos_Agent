import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

import pytest

from kratos_agent.web.server import KratosServer, KratosWebHandler


@pytest.fixture
def jobs_api(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_INTERNAL_TOKEN", "jobs-test-token")
    runtime = SimpleNamespace(workspace=tmp_path, memory=SimpleNamespace())
    server = KratosServer(("127.0.0.1", 0), KratosWebHandler, None, runtime.memory, runtime)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield server
    server.shutdown()
    server.server_close()
    worker.join()


def call(server, path, body=None, token="jobs-test-token"):
    request = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"X-Kratos-Internal-Token": token, "Content-Type": "application/json"})
    return build_opener(ProxyHandler({})).open(request, timeout=5)


def test_jobs_profile_uses_existing_internal_auth(jobs_api):
    with pytest.raises(HTTPError) as exc:
        call(jobs_api, "/api/jobs", token="")
    assert exc.value.code == 401
    status = json.load(call(jobs_api, "/api/jobs"))
    assert status["preferences"]["enabled"] is False
    assert "resume" in status["missing_profile"]


def test_profile_configuration_and_stop_are_persisted_without_submitting(jobs_api):
    result = json.load(call(jobs_api, "/api/jobs/config", {"profile": {"name": "Applicant", "email": "person@example.test", "skills": ["Python"]}, "preferences": {"daily_limit": 3}}))
    assert result["profile"]["name"] == "Applicant"
    assert result["preferences"]["daily_limit"] == 3
    assert json.load(call(jobs_api, "/api/jobs/control", {"action": "stop"}))["preferences"]["enabled"] is False
    with pytest.raises(HTTPError) as exc:
        call(jobs_api, "/api/jobs/control", {"action": "start"})
    assert exc.value.code == 400


def test_invalid_job_configuration_is_rejected(jobs_api):
    with pytest.raises(HTTPError) as exc:
        call(jobs_api, "/api/jobs/config", {"preferences": {"boards": {"ashby": ["https://localhost/private"]}}})
    assert exc.value.code == 400
    with pytest.raises(HTTPError) as exc:
        call(jobs_api, "/api/jobs/config", {"profile": []})
    assert exc.value.code == 400


def test_job_tools_are_exposed_with_the_runtime_registry(tmp_path):
    from kratos_agent.jobs.tools import register_job_tools
    from kratos_agent.core.tool_runtime import ToolRegistry
    registry = ToolRegistry()
    register_job_tools(registry, tmp_path)
    names = {tool.name for tool in registry.specs()}
    assert {"jobs_status", "jobs_scan", "jobs_apply", "jobs_autopilot"} <= names
