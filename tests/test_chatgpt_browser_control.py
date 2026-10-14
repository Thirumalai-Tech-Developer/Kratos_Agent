import json
import threading
from unittest.mock import Mock

import pytest
import requests

from kratos_agent.brain.account_store import AccountStore
from kratos_agent.brain.chatgpt_browser_control import BrowserControlMonitor, BrowserPanel, create_server
from kratos_agent.brain.chatgpt_web import ChatGPTWebAccounts
from kratos_agent.brain.config import BrainError


def test_panel_status_lists_only_public_account_fields(tmp_path):
    store = AccountStore(tmp_path)
    state = store.read()
    state.update(provider="chatgpt-web", active_web_account="one")
    state["web_accounts"] = {
        "one": {
            "email": "owner@example.com",
            "subject": "private-subject",
            "model": "chatgpt-web/test",
            "storage_state": {"cookies": [{"value": "private-cookie"}]},
            "models": [
                {
                    "id": "chatgpt-web/test",
                    "display_name": "Test",
                    "extra": "private-model-data",
                }
            ],
        }
    }
    with store.locked():
        store.write(state)
    panel = BrowserPanel(ChatGPTWebAccounts(store))
    result = panel.status()
    assert result["accounts"][0]["connected"] is True
    assert result["accounts"][0]["active"] is True
    assert "private-" not in json.dumps(result)


def test_panel_connect_failure_can_be_retried_without_false_connected_status():
    manager = Mock()
    panel = BrowserPanel(manager)
    manager.login.side_effect = BrainError("Sign in again")
    panel.busy = True
    panel._run("connect", {})
    assert panel.error == "Sign in again" and panel.busy is False
    manager.login.side_effect = None
    manager.login.return_value = {"models": [{"id": "model"}]}
    panel._run("connect", {})
    assert not panel.error and panel.message.startswith("Connected")


def test_panel_rejects_overlap_and_invalid_operations():
    panel = BrowserPanel(Mock())
    with pytest.raises(ValueError):
        panel.start("select", {"account_id": "one"})
    panel.busy = True
    with pytest.raises(RuntimeError):
        panel.start("connect", {})


def test_control_http_requires_token_and_dispatches_only_valid_actions():
    panel = Mock()
    panel.status.return_value = {"ready": True, "accounts": []}
    server = create_server(panel, "private-controller-test-token", port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    session = requests.Session()
    session.trust_env = False
    base = "http://127.0.0.1:" + str(server.server_port)
    headers = {"Authorization": "Bearer private-controller-test-token"}
    try:
        assert session.get(base + "/status").status_code == 401
        assert session.post(base + "/connect", json={}).status_code == 401
        assert session.get(base + "/status", headers=headers).json()["ready"] is True
        assert (
            session.post(base + "/open-shell", headers=headers, json={}).status_code
            == 404
        )
        assert (
            session.post(base + "/connect", headers=headers, json=[]).status_code == 400
        )
        assert (
            session.post(base + "/connect", headers=headers, json={}).status_code == 202
        )
        panel.start.assert_called_once_with("connect", {})
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_monitor_does_not_install_on_a_fresh_workspace(tmp_path, monkeypatch):
    ensure = Mock()
    monkeypatch.setattr('kratos_agent.brain.chatgpt_browser_control.ensure_browser_control', ensure)
    monitor = BrowserControlMonitor(ChatGPTWebAccounts(AccountStore(tmp_path)))
    monitor.check()
    ensure.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_monitor_retries_a_missing_panel_and_reuses_the_same_manager(tmp_path, monkeypatch):
    config = tmp_path / 'browser-extension/config.js'
    config.parent.mkdir()
    config.write_text('existing connector')
    manager = ChatGPTWebAccounts(AccountStore(tmp_path))
    ensure = Mock(side_effect=[BrainError('Unavailable'), {'running': True}])
    monkeypatch.setattr('kratos_agent.brain.chatgpt_browser_control.ensure_browser_control', ensure)
    monitor = BrowserControlMonitor(manager, source='owned-source')
    monitor.check()
    monitor.check()
    assert ensure.call_count == 2
    ensure.assert_called_with(manager, source='owned-source')


def test_monitor_prepares_extension_after_a_saved_login_is_migrated(tmp_path, monkeypatch):
    store = AccountStore(tmp_path)
    state = store.read()
    state['web_accounts'] = {'one': {'storage_state': {'cookies': []}}}
    store.write(state)
    ensure = Mock(return_value={'running': True})
    monkeypatch.setattr('kratos_agent.brain.chatgpt_browser_control.ensure_browser_control', ensure)
    manager = ChatGPTWebAccounts(store)
    BrowserControlMonitor(manager).check()
    ensure.assert_called_once_with(manager, source=None)


def test_monitor_survives_unavailable_storage_and_retries(tmp_path, monkeypatch, caplog):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path))
    retry_sync = Mock()
    monkeypatch.setattr(manager, 'retry_gateway_sync', retry_sync)
    state = {'web_accounts': {'one': {'storage_state': {'cookies': []}}}}
    monkeypatch.setattr(manager.store, 'read', Mock(side_effect=[
        RuntimeError('private-storage-detail'), state,
    ]))
    ensure = Mock(return_value={'running': True})
    monkeypatch.setattr('kratos_agent.brain.chatgpt_browser_control.ensure_browser_control', ensure)
    monitor = BrowserControlMonitor(manager)
    monitor.check()
    ensure.assert_not_called()
    retry_sync.assert_not_called()
    monitor.check()
    ensure.assert_called_once_with(manager, source=None)
    retry_sync.assert_called_once_with()
    assert 'private-storage-detail' not in caplog.text


def test_shared_store_migration_preserves_login_and_existing_references(tmp_path):
    store = AccountStore(tmp_path / 'legacy')
    state = store.read()
    state.update(browser_bridge_token='private-connection-token', active_web_account='one',
                 web_accounts={'one': {'storage_state': {'cookies': [{'value': 'private-cookie'}]}}})
    store.write(state)
    (store.root / 'browser-extension').mkdir()
    (store.root / 'browser-extension/config.js').write_text('existing extension')
    legacy_path = store.path
    manager = ChatGPTWebAccounts(store)
    assert store.promote_shared(tmp_path / 'shared')
    assert manager.store.path == tmp_path / 'shared/accounts.bin'
    assert manager.store.read()['web_accounts'] == state['web_accounts']
    assert legacy_path.exists(), 'Migration must keep the original protected store'


def test_empty_shadow_store_cannot_replace_a_real_connection(tmp_path):
    shadow = AccountStore(tmp_path / 'shadow')
    assert shadow.promote_shared(tmp_path / 'shared') is False
    assert not (tmp_path / 'shared/accounts.bin').exists()


def test_shared_store_conflict_preserves_both_records(tmp_path):
    legacy = AccountStore(tmp_path / 'legacy')
    shared = AccountStore(tmp_path / 'shared')
    first = {'accounts': {}, 'web_accounts': {'one': {}}, 'browser_bridge_token': 'first'}
    second = {'accounts': {}, 'web_accounts': {'two': {}}, 'browser_bridge_token': 'second'}
    legacy.write(first)
    shared.write(second)
    with pytest.raises(RuntimeError, match='another connection'):
        legacy.promote_shared(shared.root)
    assert legacy.read() == first and shared.read() == second
