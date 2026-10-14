from unittest.mock import Mock

import pytest

from test_chatgpt_web_connection import fixture_connection, storage
from kratos_agent.brain.config import BrainError


def test_model_refresh_uses_saved_state_without_browser_extension(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    manager.run_bridge = Mock(return_value={"subject": "owner", "storage_state": storage(), "models": []})
    manager.models()
    request = manager.run_bridge.call_args.args[0]
    assert request["storage_state"] == storage()
    assert request["account_id"] == "browser-account"


def test_saved_cookie_requests_do_not_install_or_lock_extension(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    manager.prepare_browser = Mock(side_effect=AssertionError("No extension during completion"))
    manager._run_bridge = Mock(return_value={"text": "answer"})
    result = manager.run_bridge({"mode": "complete", "storage_state": storage()}, tmp_path, 10)
    assert result["text"] == "answer"
    manager.prepare_browser.assert_not_called()


def test_cookie_rotation_updates_only_existing_bound_account(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    with manager.store.locked():
        state = manager.store.read()
        state["web_accounts"]["browser-account"]["cookie_store_id"] = "0"
        manager.store.write(state)
    refreshed = storage()
    refreshed["cookies"][0]["value"] = "new-test-session"
    manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "0", "storage_state": refreshed})
    assert manager._record()[1]["storage_state"] == refreshed
    manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "other", "storage_state": storage()})
    assert manager._record()[1]["storage_state"] == refreshed
    manager.sign_out("browser-account")
    manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "0", "storage_state": refreshed})
    with pytest.raises(BrainError):
        manager._record()


def test_logout_cookie_removal_marks_session_expired_even_with_analytics(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    with manager.store.locked():
        state = manager.store.read()
        state["web_accounts"]["browser-account"]["cookie_store_id"] = "0"
        manager.store.write(state)
    logged_out = storage()
    logged_out["cookies"][0]["name"] = "analytics"
    assert manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "0", "storage_state": logged_out})["expired"]
    assert not manager.status()["accounts"][0]["connected"]
    with pytest.raises(BrainError, match="expired"):
        manager._record()
    manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "0", "storage_state": storage()})
    assert manager._record()[1]["session_expired"] is False


def test_login_snapshot_cannot_override_operation_and_rebinds_only_current_account(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    with manager.store.locked():
        state = manager.store.read()
        state["web_accounts"]["browser-account"]["cookie_store_id"] = "0"
        manager.store.write(state)
    manager.run_bridge = Mock(return_value={"subject": "new-owner", "storage_state": storage(), "models": [], "cookie_store_id": "0"})
    result = manager.login(snapshot={"mode": "complete", "provider_id": "evil", "cookie_store_id": "0", "storage_state": storage()})
    request = manager.run_bridge.call_args.args[0]
    assert request["mode"] == "login"
    assert request["provider_id"] == "chatgpt-web"
    saved = manager.store.read()["web_accounts"]
    assert saved["browser-account"]["cookie_store_id"] is None
    assert saved[result["account_id"]]["cookie_store_id"] == "0"


def test_using_connected_model_reuses_saved_catalog_without_browser_fetch(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    model = "chatgpt-web/gpt-5-6"
    with manager.store.locked():
        state = manager.store.read()
        state["web_accounts"]["browser-account"]["models"] = [
            {"id": model, "effort_tiers": ["low", "high"]}]
        manager.store.write(state)
    manager.run_bridge = Mock(side_effect=AssertionError("Selecting a stored model must not refetch"))
    assert manager.select("browser-account", model, "high")["model"] == model
    assert manager.select("browser-account", model, "low")["reasoning_effort"] == "low"
    manager.run_bridge.assert_not_called()
