from types import SimpleNamespace
import json
from unittest.mock import Mock

import pytest

from kratos_agent.brain.account_store import AccountStore
from kratos_agent.brain.chatgpt_web import ChatGPTWebAccounts, normalize_storage
from kratos_agent.brain.config import BrainError
from kratos_agent.brain.web_providers import WEB_PROVIDERS


def snapshot(provider):
    return {"cookies": [{"name": "session", "value": "private-cookie", "domain": WEB_PROVIDERS[provider]["domains"][0], "path": "/"}], "origins": []}


@pytest.mark.parametrize("provider", list(WEB_PROVIDERS))
def test_cookie_capture_is_bound_to_its_provider(provider):
    assert normalize_storage(snapshot(provider), provider)["cookies"][0]["value"] == "private-cookie"
    invalid = {"cookies": [{"name": "session", "value": "secret", "domain": "unrelated.example", "path": "/"}], "origins": []}
    with pytest.raises(BrainError):
        normalize_storage(invalid, provider)


@pytest.mark.parametrize('provider', list(WEB_PROVIDERS))
def test_bridge_result_validates_cookies_against_the_requested_provider(tmp_path, monkeypatch, provider):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path / 'auth'))
    process = Mock()
    process.returncode = 0
    process.communicate.return_value = (json.dumps({'storage_state': snapshot(provider), 'subject': 'owner'}).encode(), b'')
    process.poll.return_value = 0
    monkeypatch.setattr('kratos_agent.brain.chatgpt_web.shutil.which', lambda name: 'node')
    monkeypatch.setattr('kratos_agent.brain.chatgpt_web.subprocess.Popen', lambda *args, **kwargs: process)
    result = manager._run_bridge({'provider_id': provider}, tmp_path, 2)
    assert result['storage_state']['cookies'][0]['domain'] == WEB_PROVIDERS[provider]['domains'][0]


def test_selected_effort_is_protected_and_forwarded_to_the_executor(tmp_path, monkeypatch):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path))
    provider = "chatgpt-web"
    record = {"subject": "owner", "storage_state": snapshot(provider), "provider_id": provider, "source": "source"}
    state = manager.store.read()
    state["web_accounts"] = {"one": record}
    manager.store.write(state)
    monkeypatch.setattr(manager, "models", lambda *_, **kwargs: [{"id": "chatgpt-web/think", "effort_tiers": ["low", "medium", "high"]}])
    monkeypatch.setattr(manager, "source", lambda value: value)
    result = manager.select("one", "chatgpt-web/think", "high")
    assert result["reasoning_effort"] == "high"
    with pytest.raises(BrainError, match="thinking level"):
        manager.select("one", "chatgpt-web/think", "unsupported")
    bridge = Mock(return_value={"subject": "owner", "text": "answer"})
    monkeypatch.setattr(manager, "run_bridge", bridge)
    manager.complete(SimpleNamespace(chatgpt_web_account_id="one"), {"model": "chatgpt-web/think", "messages": [{"role": "user", "content": "hi"}]}, 10)
    assert bridge.call_args.args[0]["payload"]["reasoning_effort"] == "high"


def test_other_cookie_providers_use_browser_web_transport(tmp_path, monkeypatch):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path))
    state = manager.store.read()
    state["web_accounts"] = {"one": {"subject": "owner", "storage_state": snapshot("qwen-browser"), "provider_id": "qwen-browser"}}
    manager.store.write(state)
    monkeypatch.setattr(manager, "models", lambda *_, **kwargs: [{"id": "qwen-browser/qwen3.7-plus", "effort_tiers": []}])
    assert manager.select("one", "qwen-browser/qwen3.7-plus")["provider"] == "browser-web"
    assert manager.store.selected_model("browser-web") == "qwen-browser/qwen3.7-plus"
