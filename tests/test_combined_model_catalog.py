"""A browser failure must not hide gateway models or change their transport."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kratos_agent.brain import config
from kratos_agent.brain.account_store import AccountStore
from kratos_agent.brain.chatgpt_web import chatgpt_web_accounts
from kratos_agent.brain.client import BrainClient
from kratos_agent.core import model_selection
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.generation_settings import GenerationSettings

WEB_MODEL = "chatgpt-web/gpt-5-6-thinking"
GATEWAY_MODEL = "openai/gpt-5.4"


@pytest.fixture(autouse=True)
def isolated_catalog_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_CATALOG_CACHE_PATH", str(tmp_path / "default-catalog.json"))
    monkeypatch.setenv("KRATOS_API_KEY", "isolated-catalog-test-key")
    reset_process_catalog(monkeypatch)


def reset_process_catalog(monkeypatch):
    for name, value in (("_cached_model_details", {}), ("_cached_models", []),
                        ("_cache_timestamp", 0.0), ("_catalog_last_attempt", 0.0),
                        ("_catalog_endpoint", ""), ("_catalog_cache_key", "")):
        monkeypatch.setattr(config, name, value, raising=False)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from kratos_agent.brain import account_store as module
    store = AccountStore(tmp_path / "auth")
    store.write({"provider": "chatgpt-web", "accounts": {}, "active_web_account": "one",
                 "web_accounts": {"one": {"provider_id": "chatgpt-web", "model": WEB_MODEL,
                                          "storage_state": {"cookies": []},
                                          "models": [{"id": WEB_MODEL, "display_name": "GPT thinking",
                                                      "supports_vision": True, "effort_tiers": ["low", "high"]}]}}})
    monkeypatch.setattr(module, "account_store", store)
    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "chatgpt-web")
    monkeypatch.setenv("KRATOS_RUNTIME_MODEL", "")
    monkeypatch.setenv("KRATOS_RUNTIME_ACCOUNT_ID", "")
    monkeypatch.setenv("KRATOS_MODEL", "")
    monkeypatch.setenv("KRATOS_BASE_URL", "http://127.0.0.1:20128/v1")
    monkeypatch.setenv("KRATOS_MODEL_ENDPOINT", "http://127.0.0.1:20128/v1/models")
    monkeypatch.setenv("KRATOS_CHAT_ENDPOINT", "http://127.0.0.1:20128/v1/chat/completions")
    return store


def gateway(monkeypatch, entries=None):
    session = Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = {"data": entries if entries is not None else [{"id": GATEWAY_MODEL, "modalities": ["text"]}]}
    monkeypatch.setattr(config.requests, "Session", lambda: session)
    return session


def test_browser_timeout_does_not_hide_gateway_or_block_picker(store, monkeypatch):
    session = gateway(monkeypatch)
    browser = Mock(side_effect=config.BrainTimeoutError("ChatGPT browser timed out"))
    monkeypatch.setattr(chatgpt_web_accounts, "models", browser)
    rows = config.get_runtime_model_catalog(strict=True)
    assert [entry["id"] for entry in rows] == [GATEWAY_MODEL, WEB_MODEL]
    assert rows[0]["connection_provider"] == "gateway"
    assert rows[1]["connection_account_id"] == "one"
    assert rows[1]["is_configured"] and rows[1]["supports_image_input"]
    assert rows[1]["effort_tiers"] == ["low", "high"]
    browser.assert_not_called()
    assert session.get.call_args.args[0] == "http://127.0.0.1:20128/v1/models"


def test_gateway_failure_leaves_saved_browser_models_selectable(store, monkeypatch):
    monkeypatch.setattr(config, "get_model_catalog", Mock(side_effect=config.ModelCatalogUnavailable("Gateway unavailable")))
    rows = config.get_runtime_model_catalog(strict=True)
    assert len(rows) == 1 and rows[0]["id"] == WEB_MODEL
    assert rows[0]["catalog_notice"] == "Gateway unavailable"


def test_failed_initial_fetch_does_not_save_a_successful_empty_snapshot(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch)
    session.get.side_effect = config.requests.Timeout("Gateway is starting")
    rows = config.get_runtime_model_catalog(strict=False, cache_path=cache)
    assert [row["id"] for row in rows] == [WEB_MODEL]
    assert "timed out" in rows[0]["catalog_notice"].lower()
    assert not cache.exists()
    session.get.side_effect = None
    rows = config.get_runtime_model_catalog(strict=False, cache_path=cache)
    assert [row["id"] for row in rows] == [GATEWAY_MODEL, WEB_MODEL]
    assert session.get.call_count == 2
    assert [row["id"] for row in json.loads(cache.read_text(encoding="utf-8"))["models"]] == [GATEWAY_MODEL]


def test_disk_catalog_preserves_unknown_modality_flags_after_memory_reset(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    endpoint = "http://127.0.0.1:20128/v1/models"
    session = gateway(monkeypatch, [{"id": GATEWAY_MODEL}])
    first = config.get_model_catalog(endpoint=endpoint, strict=True, cache_path=cache)
    original = next(row for row in first if row["id"] == GATEWAY_MODEL)
    assert original["supports_text_input"] is None
    assert original["supports_image_input"] is None
    assert original["modality_label"] == "Unknown"
    reset_process_catalog(monkeypatch)
    session.get.side_effect = AssertionError("Disk read must not refetch modality metadata")
    rows = config.get_model_catalog(endpoint=endpoint, strict=True, cache_path=cache)
    restored = next(row for row in rows if row["id"] == GATEWAY_MODEL)
    assert restored["supports_text_input"] is None
    assert restored["supports_image_input"] is None
    assert restored["modality_label"] == "Unknown"
    session.get.assert_called_once()


def test_picker_keeps_gateway_models_after_timeout_and_restart(store, monkeypatch, tmp_path):
    cache = tmp_path / 'catalog.json'
    gateway(monkeypatch)
    rows = config.get_runtime_model_catalog(strict=True, refresh=True, cache_path=cache)
    assert rows[0]['id'] == GATEWAY_MODEL
    saved = json.loads(cache.read_text(encoding='utf-8'))
    assert [row['id'] for row in saved['models']] == [GATEWAY_MODEL]
    assert 'storage_state' not in cache.read_text(encoding='utf-8')
    monkeypatch.setattr(config, 'get_model_catalog', Mock(side_effect=config.ModelCatalogUnavailable('Gateway timed out')))
    rows = config.get_runtime_model_catalog(strict=True, refresh=True, cache_path=cache)
    assert [row['id'] for row in rows] == [GATEWAY_MODEL, WEB_MODEL]
    assert rows[0]['catalog_cached'] and rows[0]['catalog_notice'] == 'Gateway timed out'


def test_catalog_is_fetched_once_and_survives_a_process_cache_reset(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch)
    initial = config.get_runtime_model_catalog(strict=True, cache_path=cache)
    assert [row["id"] for row in initial] == [GATEWAY_MODEL, WEB_MODEL]
    session.get.assert_called_once()
    reset_process_catalog(monkeypatch)
    session.get.side_effect = config.requests.Timeout("A normal read must use the saved catalog")
    for _ in range(3):
        rows = config.get_runtime_model_catalog(strict=True, cache_path=cache)
        assert [row["id"] for row in rows] == [GATEWAY_MODEL, WEB_MODEL]
    session.get.assert_called_once()


def test_only_explicit_refetch_fetches_and_replaces_the_saved_catalog(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch)
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    replacement = "openai/newly-advertised-model"
    session.get.return_value.json.return_value = {"data": [{"id": replacement}]}
    assert config.get_runtime_model_catalog(strict=True, cache_path=cache)[0]["id"] == GATEWAY_MODEL
    session.get.assert_called_once()
    rows = config.get_runtime_model_catalog(strict=True, refresh=True, cache_path=cache)
    assert [row["id"] for row in rows] == [replacement, WEB_MODEL]
    assert session.get.call_count == 2
    assert [row["id"] for row in json.loads(cache.read_text(encoding="utf-8"))["models"]] == [replacement]
    reset_process_catalog(monkeypatch)
    assert config.get_runtime_model_catalog(strict=True, cache_path=cache)[0]["id"] == replacement
    assert session.get.call_count == 2


def test_failed_explicit_refetch_preserves_last_successful_catalog_and_notice(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch)
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    saved = cache.read_text(encoding="utf-8")
    session.get.side_effect = config.requests.Timeout("Gateway is temporarily unavailable")
    rows = config.get_runtime_model_catalog(strict=True, refresh=True, cache_path=cache)
    assert [row["id"] for row in rows] == [GATEWAY_MODEL, WEB_MODEL]
    assert rows[0]["catalog_cached"] is True
    assert "timed out" in rows[0]["catalog_notice"].lower()
    assert cache.read_text(encoding="utf-8") == saved
    assert session.get.call_count == 2
    reset_process_catalog(monkeypatch)
    assert config.get_runtime_model_catalog(strict=True, cache_path=cache)[0]["id"] == GATEWAY_MODEL
    assert session.get.call_count == 2


def test_parallel_first_catalog_callers_share_one_fetch(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch)
    response = session.get.return_value
    ready = threading.Barrier(6)

    def fetch(*args, **kwargs):
        time.sleep(0.1)
        return response

    def read():
        ready.wait(timeout=5)
        return config.get_runtime_model_catalog(strict=True, cache_path=cache)

    session.get.side_effect = fetch
    with ThreadPoolExecutor(max_workers=6) as workers:
        catalogs = list(workers.map(lambda _: read(), range(6)))
    assert all([row["id"] for row in rows] == [GATEWAY_MODEL, WEB_MODEL] for rows in catalogs)
    session.get.assert_called_once()


def test_catalog_cache_is_not_reused_with_another_gateway_key(store, monkeypatch, tmp_path):
    cache = tmp_path / 'catalog.json'
    gateway(monkeypatch)
    monkeypatch.setenv('KRATOS_API_KEY', 'first-test-key')
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    monkeypatch.setenv('KRATOS_API_KEY', 'different-test-key')
    monkeypatch.setattr(config, 'get_model_catalog', Mock(side_effect=config.ModelCatalogUnavailable('Gateway timed out')))
    rows = config.get_runtime_model_catalog(strict=True, cache_path=cache)
    assert [row['id'] for row in rows] == [WEB_MODEL]


def test_successful_empty_gateway_catalog_clears_old_cache(store, monkeypatch, tmp_path):
    cache = tmp_path / 'catalog.json'
    gateway(monkeypatch)
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    monkeypatch.setattr(config, 'get_model_catalog', Mock(return_value=[]))
    config.get_runtime_model_catalog(strict=True, refresh=True, cache_path=cache)
    assert json.loads(cache.read_text(encoding='utf-8'))['models'] == []


def test_successful_empty_catalog_is_saved_and_does_not_fetch_again_after_restart(store, monkeypatch, tmp_path):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch, [])
    rows = config.get_runtime_model_catalog(strict=True, cache_path=cache)
    assert [row["id"] for row in rows] == [WEB_MODEL]
    assert json.loads(cache.read_text(encoding="utf-8"))["models"] == []
    reset_process_catalog(monkeypatch)
    session.get.side_effect = config.requests.Timeout("Empty is a successful saved catalog")
    assert [row["id"] for row in config.get_runtime_model_catalog(strict=True, cache_path=cache)] == [WEB_MODEL]
    session.get.assert_called_once()


def test_empty_catalog_without_browser_accounts_remains_a_valid_saved_result(store, monkeypatch, tmp_path):
    state = store.read()
    state["web_accounts"] = {}
    store.write(state)
    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "gateway")
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch, [])
    assert config.get_runtime_model_catalog(strict=True, cache_path=cache) == []
    reset_process_catalog(monkeypatch)
    session.get.side_effect = config.requests.Timeout("A saved empty result must not trigger a retry")
    assert config.get_runtime_model_catalog(strict=True, cache_path=cache) == []
    session.get.assert_called_once()


def test_picker_reuses_old_catalog_until_explicit_refetch(store, monkeypatch, tmp_path):
    cache = tmp_path / 'catalog.json'
    gateway(monkeypatch)
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    saved = json.loads(cache.read_text(encoding='utf-8'))
    saved['saved_at'] -= 365 * 86400
    cache.write_text(json.dumps(saved), encoding='utf-8')
    reset_process_catalog(monkeypatch)
    fetch = Mock(side_effect=config.ModelCatalogUnavailable('Gateway timed out'))
    monkeypatch.setattr(config, 'get_model_catalog', fetch)
    rows = config.get_runtime_model_catalog(strict=True, cache_path=cache)
    assert [row['id'] for row in rows] == [GATEWAY_MODEL, WEB_MODEL]
    fetch.assert_not_called()


@pytest.mark.parametrize("changed", ["endpoint", "auth"])
def test_changed_gateway_scope_fetches_its_own_catalog(store, monkeypatch, tmp_path, changed):
    cache = tmp_path / "catalog.json"
    session = gateway(monkeypatch)
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    if changed == "endpoint":
        monkeypatch.setenv("KRATOS_MODEL_ENDPOINT", "http://127.0.0.1:20129/v1/models")
    else:
        monkeypatch.setenv("KRATOS_API_KEY", "another-isolated-test-key")
    session.get.return_value.json.return_value = {"data": [{"id": "provider/other-scope-model"}]}
    rows = config.get_runtime_model_catalog(strict=True, cache_path=cache)
    assert [row["id"] for row in rows] == ["provider/other-scope-model", WEB_MODEL]
    assert session.get.call_count == 2
    if changed == "endpoint":
        assert session.get.call_args.args[0] == "http://127.0.0.1:20129/v1/models"
    else:
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer another-isolated-test-key"
    assert "isolated-test-key" not in cache.read_text(encoding="utf-8")


def test_same_model_id_keeps_distinct_gateway_and_browser_choices(store, monkeypatch):
    gateway(monkeypatch, [{"id": WEB_MODEL}])
    rows = config.get_runtime_model_catalog(strict=True)
    assert len({entry["selection_key"] for entry in rows}) == 2
    assert [entry["is_configured"] for entry in rows] == [False, True]


def runtime(workspace):
    instance = SimpleNamespace(workspace=workspace, _turn_lock=threading.RLock(), model_name=WEB_MODEL,
                               generation_settings=GenerationSettings(workspace), brain=BrainClient(),
                               loop=SimpleNamespace(), context=ContextBuilder(),
                               memory=SimpleNamespace(active_session=None), apply_model_metadata=Mock())
    return instance


def test_gateway_selection_replaces_browser_transport_and_persists_route(store, monkeypatch, tmp_path):
    original = store.read()
    rows = [{"id": GATEWAY_MODEL, "metadata_available": True, "connection_provider": "gateway",
             "selection_key": "gateway:" + GATEWAY_MODEL}]
    monkeypatch.setattr(model_selection, "get_model_catalog", lambda **kw: rows)
    instance = runtime(tmp_path / "workspace")
    model_selection.select_runtime_model(instance, GATEWAY_MODEL, rows[0]["selection_key"])
    try:
        assert instance.brain.sdk.provider == config.get_model_provider() == "gateway"
        assert instance.brain.sdk.endpoint_url == "http://127.0.0.1:20128/v1/chat/completions"
        assert instance.brain.sdk._require_configured_model(GATEWAY_MODEL) == GATEWAY_MODEL
        assert model_selection.read_selected_connection(instance.workspace)["provider"] == "gateway"
        assert store.read() == original  # Selecting a runtime model does not change saved logins.
    finally:
        instance.brain.session.close()


def test_model_selection_uses_the_saved_workspace_catalog_without_refetch(store, monkeypatch, tmp_path):
    session = gateway(monkeypatch)
    instance = runtime(tmp_path / "workspace")
    cache = instance.workspace / ".kratos" / "gateway-model-catalog.json"
    config.get_runtime_model_catalog(strict=True, cache_path=cache)
    session.get.assert_called_once()
    reset_process_catalog(monkeypatch)
    session.get.side_effect = config.requests.Timeout("Selecting a saved model must not refetch")
    try:
        model_selection.select_runtime_model(instance, GATEWAY_MODEL, "gateway:" + GATEWAY_MODEL)
        assert instance.model_name == GATEWAY_MODEL
        assert instance.brain.sdk.provider == "gateway"
        session.get.assert_called_once()
    finally:
        instance.brain.session.close()


def test_selection_waits_for_slow_live_gateway_catalog(store, monkeypatch, tmp_path):
    session = gateway(monkeypatch)
    response = session.get.return_value
    def slow_catalog(*args, **kwargs):
        if kwargs['timeout'] < 6:
            raise config.requests.Timeout('Catalog discovery needs six seconds')
        return response
    session.get.side_effect = slow_catalog
    instance = runtime(tmp_path / 'workspace')
    try:
        model_selection.select_runtime_model(instance, GATEWAY_MODEL, 'gateway:' + GATEWAY_MODEL)
        assert instance.model_name == GATEWAY_MODEL
        assert instance.brain.sdk.provider == 'gateway'
    finally:
        instance.brain.session.close()


def test_selection_routes_same_id_to_explicit_account(store, monkeypatch, tmp_path):
    gateway(monkeypatch, [{"id": WEB_MODEL}])
    rows = config.get_runtime_model_catalog(strict=True)
    monkeypatch.setattr(model_selection, "get_model_catalog", lambda **kw: rows)
    instance = runtime(tmp_path / "workspace")
    model_selection.select_runtime_model(instance, WEB_MODEL, rows[0]["selection_key"])
    assert instance.brain.sdk.provider == "gateway"
    model_selection.select_runtime_model(instance, WEB_MODEL, rows[1]["selection_key"])
    try:
        assert instance.brain.sdk.provider == "chatgpt-web"
        assert instance.brain.sdk.chatgpt_web_account_id == "one"
        instance.brain.sdk._check_active_connection()
        payload = json.loads((instance.workspace / ".kratos/model-selection.json").read_text())
        assert payload == {"model": WEB_MODEL, "provider": "chatgpt-web", "account_id": "one"}
        changed = store.read()
        changed["web_accounts"]["one"].pop("storage_state")
        store.write(changed)
        with pytest.raises(config.BrainError, match="disconnected"):
            instance.brain.sdk._check_active_connection()
    finally:
        instance.brain.session.close()


def test_failed_selection_preserves_browser_connection_and_environment(store, monkeypatch, tmp_path):
    monkeypatch.setattr(model_selection, "get_model_catalog", lambda **kw: [{"id": GATEWAY_MODEL, "metadata_available": True}])
    monkeypatch.setattr(model_selection, "_save_selected_model", Mock(side_effect=PermissionError()))
    instance = runtime(tmp_path / "workspace")
    before = instance.brain
    try:
        with pytest.raises(OSError):
            model_selection.select_runtime_model(instance, GATEWAY_MODEL)
        assert instance.brain is before and instance.brain.sdk.provider == config.get_model_provider() == "chatgpt-web"
        assert config.get_default_model() == WEB_MODEL
    finally:
        instance.brain.session.close()
