import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import requests
from test_chatgpt_web_connection import fixture_connection, storage

from kratos_agent.brain.chatgpt_browser_control import BrowserPanel
from kratos_agent.brain.gateway_cookie_sync import sync_gateway_cookies


@pytest.fixture
def local_hop(monkeypatch):
    monkeypatch.setenv("KRATOS_GATEWAY_URL", "http://127.0.0.1:20128")
    monkeypatch.setenv("OMNIROUTE_INTERNAL_SERVICE_TOKEN", "private-local-service-token")
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = Mock(ok=True, status_code=200)
    session.post.return_value.json.return_value = {
        "synced": True, "provider": "chatgpt-web-codex", "usage": "native_codex_only",
        "connection_id": "owned-connection", "action": "sync", "enabled": True,
    }
    monkeypatch.setattr("kratos_agent.brain.gateway_cookie_sync.requests.Session", lambda: session)
    return session


def test_local_service_hop_uses_header_auth_and_never_proxy_or_redirect(local_hop):
    result = sync_gateway_cookies("a" * 24, {"storage_state": storage()})
    assert result["synced"] and result["usage"] == "native_codex_only"
    args, kwargs = local_hop.post.call_args
    assert args == ("http://127.0.0.1:20128/api/kratos/browser-cookies",)
    assert local_hop.trust_env is False
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"]["storage_state"] == storage()
    assert kwargs["headers"] == {"x-omniroute-internal-service-token": "private-local-service-token"}
    assert "storage_state" not in result and storage()["cookies"][0]["value"] not in json.dumps(result)


@pytest.mark.parametrize("url", ["https://example.com", "http://127.0.0.1@evil.example", "http://127.0.0.1:20128/path", "http://127.0.0.1:20128/?token=x"])
def test_cookie_credentials_cannot_be_forwarded_off_host_or_to_another_path(local_hop, monkeypatch, url):
    monkeypatch.setenv("KRATOS_GATEWAY_URL", url)
    assert not sync_gateway_cookies("a" * 24, {"storage_state": storage()})["synced"]
    local_hop.post.assert_not_called()


@pytest.mark.parametrize("status", [302, 400, 401, 403, 409, 413, 503])
def test_failed_service_hop_retains_retry_and_exposes_only_fixed_messages(local_hop, status):
    local_hop.post.return_value.ok = False
    local_hop.post.return_value.status_code = status
    local_hop.post.return_value.json.side_effect = AssertionError("Never read an error response containing secrets")
    result = sync_gateway_cookies("a" * 24, {"storage_state": storage()})
    assert not result["synced"] and result["pending"]
    assert result["error"]
    local_hop.post.return_value.json.assert_not_called()


def test_transport_errors_never_copy_private_exception_text(local_hop):
    local_hop.post.side_effect = requests.ConnectionError("private-local-service-token secret-cookie")
    result = sync_gateway_cookies("a" * 24, {"storage_state": storage()})
    assert "secret-cookie" not in json.dumps(result)


def test_expired_or_disconnected_hop_sends_no_stale_credentials(local_hop):
    local_hop.post.return_value.json.return_value.update(action="disconnect", enabled=False)
    result = sync_gateway_cookies("a" * 24, {"storage_state": storage()}, "disconnect")
    assert result["synced"] and not result["enabled"]
    assert local_hop.post.call_args.kwargs["json"] == {"provider": "chatgpt-web", "account_id": "a" * 24, "action": "disconnect"}


def test_login_cookie_refresh_and_disconnect_forward_to_service(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    calls = []

    def sync(key, record, action):
        calls.append((key, record.get("storage_state"), action))
        return {"synced": True, "pending": False, "action": action, "enabled": action == "sync", "usage": "native_codex_only"}

    monkeypatch.setattr("kratos_agent.brain.gateway_cookie_sync.sync_gateway_cookies", sync)
    manager.run_bridge = Mock(return_value={"subject": "owner", "storage_state": storage(), "models": [], "cookie_store_id": "0"})
    account = manager.login(snapshot={"cookie_store_id": "0", "storage_state": storage()})["account_id"]
    manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "0", "storage_state": storage()})
    manager.sync_snapshot("chatgpt-web", {"cookie_store_id": "0", "storage_state": {"cookies": [], "origins": []}})
    manager.sign_out(account)
    assert [call[2] for call in calls] == ["sync", "sync", "expired", "disconnect"]
    assert calls[-1][1] is None
    status = BrowserPanel(manager).status()["accounts"][-1]["gateway_sync"]
    assert status["synced"] and not status["enabled"]
    assert storage()["cookies"][0]["value"] not in json.dumps(status)


def test_failed_sync_is_retried_without_collecting_cookies_or_fetching_models(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    manager.run_bridge = Mock(side_effect=AssertionError("No browser/model fetch during service retry"))
    sync = Mock(return_value={"synced": True, "pending": False, "action": "sync", "enabled": True})
    monkeypatch.setattr("kratos_agent.brain.gateway_cookie_sync.sync_gateway_cookies", sync)
    assert manager.retry_gateway_sync() == 1
    assert manager.retry_gateway_sync() == 0
    assert sync.call_count == 1
    manager.run_bridge.assert_not_called()


def test_newer_credentials_do_not_receive_an_old_sync_acknowledgement(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)

    def sync(*_):
        with manager.store.locked():
            state = manager.store.read()
            state["web_accounts"]["browser-account"]["storage_state"]["cookies"][0]["value"] = "newer-secret"
            state["web_accounts"]["browser-account"]["gateway_sync"] = {"pending": True, "synced": False}
            manager.store.write(state)
        return {"synced": True, "pending": False, "action": "sync"}

    monkeypatch.setattr("kratos_agent.brain.gateway_cookie_sync.sync_gateway_cookies", sync)
    manager.sync_gateway_account("browser-account")
    assert manager.store.read()["web_accounts"]["browser-account"]["gateway_sync"]["pending"]


def test_waiting_sender_reads_latest_credentials_after_acquiring_its_lease(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)

    @contextmanager
    def lease(*_):
        # Caller B completed a newer refresh while caller A waited for its lease.
        with manager.store.locked():
            state = manager.store.read()
            state["web_accounts"]["browser-account"]["storage_state"]["cookies"][0]["value"] = "newest-session"
            state["web_accounts"]["browser-account"]["gateway_sync"] = {"pending": False, "synced": True, "action": "sync"}
            manager.store.write(state)
        yield 3

    posted = []

    def sync(_key, record, action):
        posted.append(record["storage_state"]["cookies"][0]["value"])
        return {"synced": True, "pending": False, "action": action}

    monkeypatch.setattr(manager, "session_lock", lease)
    monkeypatch.setattr("kratos_agent.brain.gateway_cookie_sync.sync_gateway_cookies", sync)
    manager.sync_gateway_account("browser-account")
    assert posted == ["newest-session"]
