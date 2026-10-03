import ast
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import requests

from kratos_agent.brain import config
from kratos_agent.brain.client import BrainClient
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.generation_settings import GenerationSettings
from kratos_agent.core.model_adapter import KratosModelAdapter
from kratos_agent.core import model_selection
from kratos_agent.web.server import KratosServer, KratosWebHandler


OLD = "ds-web/deepseek-v4-pro"
NEW = "qwen-browser/qwen3.6-plus"
CATALOG = [
    {"id": OLD, "name": "DeepSeek", "provider": "ds-web", "metadata_available": True,
     "supports_temperature": True, "max_output_tokens": 1024, "context_length": 4096},
    {"id": NEW, "name": "Qwen", "provider": "qwen-browser", "metadata_available": True,
     "supports_image_input": True, "supports_temperature": True,
     "max_output_tokens": 8192, "context_length": 131072, "effort_tiers": ["low", "high"]},
]


@pytest.fixture(autouse=True)
def isolate_catalog_cache(monkeypatch):
    for key, value in (("_cached_model_details", {}), ("_cached_models", []),
                       ("_cache_timestamp", 0.0), ("_catalog_last_attempt", 0.0),
                       ("_catalog_endpoint", "")):
        monkeypatch.setattr(config, key, value)


def real_metadata_method():
    # Compile only this method to avoid composition-root startup and global tool discovery.
    path = Path(__file__).parents[1] / "src/kratos_agent/main.py"
    cls = next(item for item in ast.parse(path.read_text(encoding="utf-8")).body
               if isinstance(item, ast.ClassDef) and item.name == "KratosRuntime")
    method = next(item for item in cls.body if isinstance(item, ast.FunctionDef)
                  and item.name == "apply_model_metadata")
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["apply_model_metadata"]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", OLD)
    monkeypatch.setattr(model_selection, "get_model_catalog", lambda **kwargs: CATALOG)
    settings = GenerationSettings(tmp_path)
    settings.update(OLD, CATALOG[0], {"temperature": 0.8})
    settings.update(NEW, CATALOG[1], {"temperature": 0.2, "reasoning_effort": "high", "inspection_limit": 5})
    client = BrainClient("http://127.0.0.1:1/v1/chat/completions")
    instance = SimpleNamespace(
        workspace=tmp_path, model_name=OLD, _turn_lock=threading.RLock(), brain=client,
        generation_settings=settings, model_metadata=CATALOG[0], context=ContextBuilder(),
        memory=SimpleNamespace(active_session=SimpleNamespace(model=OLD), save=Mock()),
        harness=SimpleNamespace(get_plugin=Mock(return_value=SimpleNamespace(set_model=Mock()))),
    )
    instance.model = KratosModelAdapter(OLD, client)
    instance.loop = SimpleNamespace(model=instance.model, inspection_limit=12)
    instance.apply_model_metadata = lambda metadata: real_metadata_method()(instance, metadata)
    instance.set_model = lambda model: model_selection.select_runtime_model(instance, model)
    yield instance
    instance.brain.session.close()


def test_explicit_choice_updates_request_runtime_session_capabilities_and_persistence(runtime):
    runtime.set_model(NEW)
    assert runtime.model_name == config.get_default_model() == NEW
    assert runtime.loop.model is runtime.model
    assert runtime.model.model == NEW and runtime.model.client is runtime.brain
    request = runtime.brain.build_envelope(NEW, [])
    assert request["model"] == NEW
    assert request["temperature"] == 0.2 and request["reasoning_effort"] == "high"
    assert runtime.loop.inspection_limit == 5
    assert runtime.context.budget.max_input_tokens == 131072
    assert runtime.context.budget.reserve_output_tokens == 8192
    assert runtime.memory.active_session.model == NEW
    runtime.memory.save.assert_called_once()
    runtime.harness.get_plugin.return_value.set_model.assert_called_once_with(NEW)
    assert model_selection.read_selected_model(runtime.workspace) == NEW
    # Settings stay scoped to their model when selecting the previous one again.
    runtime.set_model(OLD)
    assert runtime.brain.build_envelope(OLD, [])["temperature"] == 0.8
    assert "reasoning_effort" not in runtime.brain.generation_options


@pytest.mark.parametrize("model", [None, [], "", " model", "model\n", "x" * 513, "other/not-advertised"])
def test_invalid_and_unknown_choice_preserves_current_runtime(runtime, model):
    with pytest.raises(ValueError):
        runtime.set_model(model)
    assert runtime.model_name == config.get_default_model() == OLD
    assert model_selection.read_selected_model(runtime.workspace) is None


def test_missing_catalog_and_failed_persistence_do_not_switch(runtime, monkeypatch):
    def unavailable(**kwargs):
        raise config.ModelCatalogUnavailable("The gateway model catalog timed out.")
    monkeypatch.setattr(model_selection, "get_model_catalog", unavailable)
    with pytest.raises(config.ModelCatalogUnavailable):
        runtime.set_model(NEW)
    monkeypatch.setattr(model_selection, "get_model_catalog", lambda **kwargs: CATALOG)
    monkeypatch.setattr(model_selection, "_save_selected_model", Mock(side_effect=PermissionError()))
    with pytest.raises(OSError):
        runtime.set_model(NEW)
    assert runtime.model_name == config.get_default_model() == OLD


def hold_runtime_lock(runtime):
    started, release = threading.Event(), threading.Event()
    def hold():
        with runtime._turn_lock:
            started.set()
            release.wait(10)
    worker = threading.Thread(target=hold)
    worker.start()
    assert started.wait(3)
    return release, worker


def test_direct_model_selection_rejects_active_runtime_turn(runtime):
    release, worker = hold_runtime_lock(runtime)
    try:
        with pytest.raises(model_selection.ModelSelectionBusy):
            runtime.set_model(NEW)
    finally:
        release.set()
        worker.join(3)
    assert runtime.model_name == OLD


@pytest.fixture
def server(runtime, monkeypatch):
    monkeypatch.setenv("KRATOS_INTERNAL_TOKEN", "model-test-token")
    monkeypatch.setattr(config, "get_model_catalog", lambda **kwargs: CATALOG)
    instance = KratosServer(("127.0.0.1", 0), KratosWebHandler, Mock(), Mock(), runtime)
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    worker.join(3)


def call(server, payload=None):
    request = Request(f"http://127.0.0.1:{server.server_port}/api/models",
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json", "X-Kratos-Internal-Token": "model-test-token"})
    return json.load(build_opener(ProxyHandler({})).open(request, timeout=5))


def test_api_returns_catalog_capabilities_and_selects_model(server):
    listing = call(server)
    assert listing["model"] == OLD
    assert listing["models"][1]["supports_image_input"] is True
    response = call(server, {"model": NEW})
    assert response["status"] == "ok" and response["model"] == NEW
    assert response["settings"]["options"]["reasoning_effort"] == "high"
    assert not server.turn_lock.locked()


@pytest.mark.parametrize("payload", [{}, [], {"model": NEW, "other": True}, {"model": "unknown"}, {"model": True}])
def test_api_rejects_unknown_and_malformed_ids(server, payload):
    with pytest.raises(HTTPError) as exc:
        call(server, payload)
    assert exc.value.code == 400
    assert server.runtime.model_name == OLD and not server.turn_lock.locked()


def test_api_rejects_both_active_turn_locks(server):
    server.turn_lock.acquire()
    try:
        with pytest.raises(HTTPError) as exc:
            call(server, {"model": NEW})
        assert exc.value.code == 409
    finally:
        server.turn_lock.release()
    release, worker = hold_runtime_lock(server.runtime)
    try:
        with pytest.raises(HTTPError) as exc:
            call(server, {"model": NEW})
        assert exc.value.code == 409
    finally:
        release.set()
        worker.join(3)
    assert not server.turn_lock.locked()


def test_api_reports_catalog_timeout(server, monkeypatch):
    def fail(**kwargs):
        raise config.ModelCatalogUnavailable("The gateway model catalog timed out.")
    monkeypatch.setattr(config, "get_model_catalog", fail)
    monkeypatch.setattr(model_selection, "get_model_catalog", fail)
    for payload in (None, {"model": NEW}):
        with pytest.raises(HTTPError) as exc:
            call(server, payload)
        assert exc.value.code == 503
        assert "timed out" in json.load(exc.value)["error"]
    assert not server.turn_lock.locked() and server.runtime.model_name == OLD


def test_strict_catalog_preserves_names_provider_and_unknown_modalities(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"data": [{"id": NEW, "name": "Qwen Plus", "owned_by": "Qwen",
                                            "input_modalities": ["text", "image"]}, {"id": OLD}]}
    monkeypatch.setattr(requests.Session, "get", Mock(return_value=response))
    listing = config.get_model_catalog(refresh=True, strict=True)
    qwen = next(entry for entry in listing if entry["id"] == NEW)
    assert qwen["name"] == "Qwen Plus" and qwen["provider"] == "Qwen"
    assert qwen["supports_image_input"] is True
    deepseek = next(entry for entry in listing if entry["id"] == OLD)
    assert deepseek["supports_image_input"] is None


def test_strict_catalog_never_accepts_stale_data_after_timeout(monkeypatch):
    monkeypatch.setattr(requests.Session, "get", Mock(side_effect=requests.Timeout()))
    monkeypatch.setattr(config, "_cached_model_details", {NEW: {"id": NEW}})
    with pytest.raises(config.ModelCatalogUnavailable, match="timed out"):
        config.get_model_catalog(refresh=True, strict=True)


def test_model_listing_cache_tracks_explicit_selection(monkeypatch):
    import time
    monkeypatch.setenv("KRATOS_MODEL", NEW)
    monkeypatch.setattr(config, "_cached_models", [OLD])
    monkeypatch.setattr(config, "_cached_model_details", {OLD: {"id": OLD}, NEW: {"id": NEW}})
    monkeypatch.setattr(config, "_cache_timestamp", time.time())
    assert config.get_available_models() == [NEW]


def test_saved_selection_is_applied_to_studio_environment(tmp_path, monkeypatch):
    from kratos_agent import product
    monkeypatch.setenv("KRATOS_MODEL", OLD)
    model_selection._save_selected_model(tmp_path, NEW)
    args = SimpleNamespace(workspace=tmp_path, agent_port=20127, port=20128, data_dir=None)
    assert product.prepare_environment(args)["KRATOS_MODEL"] == NEW
