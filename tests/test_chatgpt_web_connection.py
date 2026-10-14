import json
import subprocess
import sys
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from kratos_agent.brain.account_store import AccountStore
from kratos_agent.brain.chatgpt_web import (
    ChatGPTWebAccounts,
    browser_completion,
    browser_payload,
    normalize_storage,
)
from kratos_agent.brain.config import BrainError, BrainToolCallError
from kratos_agent.core.archive import redact
from kratos_agent.sdk.client import KratosClient


def storage(domain=".chatgpt.com", expiry=-1):
    return {
        "cookies": [
            {
                "name": "__Secure-next-auth.session-token",
                "value": "private-browser-cookie-value",
                "domain": domain,
                "path": "/",
                "expires": expiry,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }


def fixture_connection(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "outside-workspace")
    state = store.read()
    state.update(provider="chatgpt-web", active_web_account="browser-account")
    state["web_accounts"] = {
        "browser-account": {
            "storage_state": storage(),
            "subject": "owner",
            "model": "chatgpt-web/gpt-5-6",
            "source": str(tmp_path),
        }
    }
    with store.locked():
        store.write(state)
    manager = ChatGPTWebAccounts(store)
    monkeypatch.setattr("kratos_agent.brain.account_store.account_store", store)
    monkeypatch.setattr("kratos_agent.brain.chatgpt_web.chatgpt_web_accounts", manager)
    monkeypatch.delenv("KRATOS_MODEL_PROVIDER", raising=False)
    monkeypatch.setattr(manager, "source", lambda *_: tmp_path)
    return manager


@pytest.mark.parametrize(
    "domain", ["chatgpt.com.example.net", "example.net", ".evilopenai.com"]
)
def test_unrelated_cookies_rejected(domain):
    with pytest.raises(BrainError, match="belong"):
        normalize_storage(storage(domain))


def test_expired_cookie_and_unrelated_origin_rejected():
    with pytest.raises(BrainError, match="unexpired"):
        normalize_storage(storage(expiry=1))
    value = storage()
    value["origins"] = [{"origin": "https://example.net", "localStorage": []}]
    with pytest.raises(BrainError, match="belong"):
        normalize_storage(value)


def test_browser_credentials_encrypted_and_never_in_status_or_archive(
    tmp_path, monkeypatch
):
    manager = fixture_connection(tmp_path, monkeypatch)
    assert storage()["cookies"][0]["value"] not in json.dumps(manager.status())
    manager.store.read()  # Registers persisted cookie secrets, including after a restart.
    assert redact("private-browser-cookie-value") == "[REDACTED]"
    if sys.platform == "win32":
        assert b"private-browser-cookie-value" not in manager.store.path.read_bytes()


def test_local_tool_history_becomes_text_and_validated_calls():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    request = browser_payload(
        {
            "model": "chatgpt-web/gpt-5-6",
            "tools": tools,
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "file result"},
            ],
        }
    )
    assert "tools" not in request and request["stream"] is False
    assert all(
        "tool_calls" not in item and item["role"] != "tool"
        for item in request["messages"]
    )
    valid = browser_completion(
        json.dumps(
            {
                "text": "",
                "tool_calls": [
                    {"name": "read_file", "arguments": {"path": "README.md"}}
                ],
            }
        ),
        tools,
    )
    assert valid.tool_calls[0].name == "read_file"
    for body in [
        "call:read_file{}",
        '{"text":"","tool_calls":[{"name":"delete_everything","arguments":{}}]}',
        '{"text":"","tool_calls":[{"name":"read_file","arguments":{"path":1}}]}',
    ]:
        with pytest.raises(BrainToolCallError, match="no tool was executed"):
            browser_completion(body, tools)


def test_browser_final_text_does_not_require_or_invent_tool_calls():
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
        "additionalProperties": False,
    }}}]
    answer = browser_completion("Hi Thiru! How can I help you today?", tools)
    assert answer.text == "Hi Thiru! How can I help you today?"
    assert not answer.tool_calls
    for choice in ("required", {"type": "function", "function": {"name": "read_file"}}):
        with pytest.raises(BrainToolCallError):
            browser_completion("Hi!", tools, choice)
    for invalid in ('{"tool_calls":', 'Here is the call: {"tool_calls": []}', 'call:read_file{}'):
        with pytest.raises(BrainToolCallError):
            browser_completion(invalid, tools)
    fenced = '```json\n{"text":"","tool_calls":[{"name":"read_file","arguments":{"path":"README.md"}}]}\n```'
    assert browser_completion(fenced, tools).tool_calls[0].name == "read_file"
    with pytest.raises(BrainToolCallError):
        browser_completion(fenced.replace('"README.md"', '42'), tools)
    with pytest.raises(BrainToolCallError):
        browser_completion('{"text":"done","tool_calls":[]}', tools, "required")


def test_browser_tool_choice_none_never_executes_tools():
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    request = browser_payload({"model":"chatgpt-web/gpt-5-5-thinking", "messages": [{"role":"user","content":"hi"}], "tools":tools, "tool_choice":"none"})
    assert len(request["messages"]) == 1
    answer = browser_completion('{"text":"","tool_calls":[{"name":"read_file","arguments":{}}]}', tools, "none")
    assert not answer.tool_calls


def test_sdk_routes_through_browser_and_refreshes_encrypted_cookies(
    tmp_path, monkeypatch
):
    manager = fixture_connection(tmp_path, monkeypatch)
    changed = storage()
    changed["cookies"][0]["value"] = "renewed-browser-cookie-value"
    manager.run_bridge = Mock(
        return_value={
            "subject": "owner",
            "storage_state": changed,
            "text": "answer",
            "models": [],
        }
    )
    client = KratosClient()
    client.session.post = Mock(
        side_effect=AssertionError("Gateway must not receive browser requests")
    )
    chunks = []
    result = client.complete(
        client.build_request(
            "chatgpt-web/gpt-5-6", [{"role": "user", "content": "hello"}]
        ),
        on_chunk=chunks.append,
    )
    assert result.text == "answer" and chunks == ["answer"]
    assert (
        manager.store.read()["web_accounts"]["browser-account"]["storage_state"]
        == changed
    )
    assert manager.run_bridge.call_args.args[0]["payload"]["stream"] is False


def test_account_change_and_signout_never_restore_old_session(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    key, record = manager._record()
    with pytest.raises(BrainError, match="changed accounts"):
        manager._save_refresh(
            key, record, {"subject": "someone-else", "storage_state": storage()}
        )
    manager.sign_out(key)
    with pytest.raises(BrainError, match="disconnected"):
        manager._save_refresh(
            key, record, {"subject": "owner", "storage_state": storage()}
        )


def test_cancelled_turn_does_not_open_browser(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    manager.run_bridge = Mock()
    cancel = Event()
    cancel.set()
    with pytest.raises(BrainError, match="cancelled"):
        manager.complete(
            KratosClient(), {"model": "chatgpt-web/gpt-5-6"}, 30, cancel=cancel
        )
    manager.run_bridge.assert_not_called()


def test_registered_connection_cli_is_importable():
    from importlib.metadata import entry_points

    entry = next(
        item
        for item in entry_points(group="console_scripts")
        if item.name == "kratos-connect"
    )
    assert callable(entry.load())
    command = Path(sys.executable).parent / (
        "kratos-connect.exe" if sys.platform == "win32" else "kratos-connect"
    )
    result = subprocess.run(
        [str(command), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0 and "web-login" in result.stdout


def test_client_cannot_continue_after_account_switch(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    client = KratosClient()
    state = manager.store.read()
    state["active_web_account"] = "other-account"
    with manager.store.locked():
        manager.store.write(state)
    manager.run_bridge = Mock()
    with pytest.raises(BrainError, match="account changed"):
        client.complete({"model": "chatgpt-web/gpt-5-6", "messages": []})
    manager.run_bridge.assert_not_called()


def test_same_account_turns_read_latest_refreshed_cookies(tmp_path, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    manager = fixture_connection(tmp_path, monkeypatch)
    observed = []

    def turn(request, *_):
        observed.append(
            manager.store.read()["web_accounts"]["browser-account"]["storage_state"][
                "cookies"
            ][0]["value"]
        )
        time.sleep(0.05)
        value = storage()
        value["cookies"][0]["value"] = "renewed-session-" + str(len(observed))
        return {
            "subject": "owner",
            "storage_state": value,
            "text": "done",
            "models": [],
        }

    manager.run_bridge = turn
    client = KratosClient()
    with ThreadPoolExecutor(max_workers=2) as workers:
        requests = [
            workers.submit(
                manager.complete,
                client,
                {"model": "chatgpt-web/gpt-5-6", "messages": []},
                5,
            )
            for _ in range(2)
        ]
        assert [request.result().text for request in requests] == ["done", "done"]
    assert observed == ["private-browser-cookie-value", "renewed-session-1"]


def test_cookie_refresh_does_not_capture_completion_text(tmp_path, monkeypatch):
    manager = fixture_connection(tmp_path, monkeypatch)
    key, record = manager._record()
    manager._save_refresh(
        key,
        record,
        {
            "subject": "owner",
            "storage_state": storage(),
            "models": [],
            "text": "transient completion",
        },
    )
    assert "text" not in manager.store.read()["web_accounts"][key]


def test_studio_cli_uses_connected_model_without_gateway_catalog(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from kratos_agent import product

    fixture_connection(tmp_path, monkeypatch)
    monkeypatch.setattr(product, "prepare_environment", lambda _: {})
    terminal = Mock()
    gateway = Mock(
        side_effect=AssertionError("Account models do not require gateway discovery")
    )
    monkeypatch.setattr(product, "launch_terminal", terminal)
    monkeypatch.setattr(product, "gateway_service", gateway)
    product.run_cli(SimpleNamespace(workspace=tmp_path))
    assert terminal.call_args.args[1]["KRATOS_MODEL"] == "chatgpt-web/gpt-5-6"
    gateway.assert_not_called()


def test_cli_login_defaults_to_regular_browser_not_oauth(tmp_path, monkeypatch, capsys):
    from kratos_agent.brain import chatgpt_auth

    manager = fixture_connection(tmp_path, monkeypatch)
    manager.login = Mock(return_value={"account_id": "browser-account", "models": []})
    oauth = Mock(
        side_effect=AssertionError(
            "Default login must use the supplied browser executor"
        )
    )
    monkeypatch.setattr(chatgpt_auth.chatgpt_accounts, "start_login", oauth)
    opened = Mock()
    monkeypatch.setattr(chatgpt_auth.webbrowser, "open", opened)
    monkeypatch.setattr(sys, "argv", ["kratos-connect", "login"])
    chatgpt_auth.connection_main()
    manager.login.assert_called_once_with(source=None)
    opened.assert_called_once_with("https://chatgpt.com")
    assert "regular Chrome or Edge" in capsys.readouterr().out
    oauth.assert_not_called()


def test_extension_setup_stays_outside_project_and_preserves_token(tmp_path):
    manager = ChatGPTWebAccounts(AccountStore(tmp_path / "user-auth"))
    initial = manager.prepare_browser()
    later = manager.prepare_browser()
    assert initial["token"] == later["token"]
    assert initial["port"] == later["port"]
    assert initial["control_port"] == later["control_port"]
    assert initial["port"] != initial["control_port"]
    root = Path(initial["directory"])
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["permissions"] == ["cookies", "alarms", "storage"]
    assert manifest["action"]["default_popup"] == "popup.html"
    assert (root / "popup.js").is_file() and (root / "popup.css").is_file()
    assert set(manifest["content_scripts"][0]["matches"]) == {
        "https://chatgpt.com/*", "https://chat.qwen.ai/*", "https://www.dola.com/*",
        "https://gemini.google.com/*", "https://chat.deepseek.com/*",
        "https://www.kimi.ai/*", "https://www.meta.ai/*", "https://chat.groq.com/*",
        "https://grok.com/*", "https://claude.ai/*", "https://www.perplexity.ai/*", "https://chat.z.ai/*",
    }
    assert "accounts.google.com" not in json.dumps(manifest)
    assert manager.store.path.parent == root.parent
    assert redact(initial["token"]) == "[REDACTED]"


def test_reserved_browser_ports_are_replaced_without_losing_login(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import requests
    local = MagicMock()
    local.__enter__.return_value = local
    local.get.side_effect = requests.ConnectionError('No receiver')
    monkeypatch.setattr(requests, 'Session', lambda: local)
    manager = ChatGPTWebAccounts(AccountStore(tmp_path / 'auth'))
    state = manager.store.read()
    state.update(browser_bridge_token='private-existing-browser-token-long-enough', browser_bridge_port=20001,
                 browser_control_port=20002, web_accounts={'one': {'storage_state': storage()}})
    manager.store.write(state)
    import socket
    original_socket = socket.socket

    class ReservedPortSocket:
        def __init__(self):
            self.real = original_socket()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.real.close()
        def bind(self, address):
            if address[1] in (20001, 20002):
                raise PermissionError('Reserved Windows port')
            return self.real.bind(address)
        def getsockname(self):
            return self.real.getsockname()
        def listen(self, backlog):
            return self.real.listen(backlog)

    monkeypatch.setattr('kratos_agent.brain.chatgpt_web.socket.socket', ReservedPortSocket)
    setup = manager.prepare_browser()
    assert setup['port'] not in (20001, 20002) and setup['control_port'] not in (20001, 20002)
    assert setup['token'] == state['browser_bridge_token']
    assert manager.store.read()['web_accounts'] == state['web_accounts']


def test_browser_setup_command_does_not_print_connection_token(
    tmp_path, monkeypatch, capsys
):
    from kratos_agent.brain import chatgpt_auth

    manager = fixture_connection(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "kratos_agent.brain.chatgpt_browser_control.ensure_browser_control",
        lambda *_, **__: {"running": True},
    )
    monkeypatch.setattr(sys, "argv", ["kratos-connect", "browser-setup"])
    chatgpt_auth.connection_main()
    output = capsys.readouterr().out
    assert "extension_directory" in output
    assert manager.store.read()["browser_bridge_token"] not in output


@pytest.mark.parametrize("command", ["status", "models", "select", "signout"])
def test_default_commands_use_browser_connection(tmp_path, monkeypatch, command):
    from kratos_agent.brain import chatgpt_auth

    manager = fixture_connection(tmp_path, monkeypatch)
    operation = "sign_out" if command == "signout" else command
    method = Mock(return_value={"ok": True})
    monkeypatch.setattr(manager, operation, method)
    args = ["kratos-connect", command, "--account", "browser-account"]
    if command == "select":
        args += ["--model", "chatgpt-web/gpt-5-6"]
    monkeypatch.setattr(sys, "argv", args)
    chatgpt_auth.connection_main()
    method.assert_called_once()


def test_official_oauth_is_explicit(tmp_path, monkeypatch):
    from kratos_agent.brain import chatgpt_auth

    fixture_connection(tmp_path, monkeypatch)
    status = Mock(return_value={"provider": "chatgpt"})
    monkeypatch.setattr(chatgpt_auth.chatgpt_accounts, "status", status)
    monkeypatch.setattr(
        sys, "argv", ["kratos-connect", "status", "--provider", "chatgpt"]
    )
    chatgpt_auth.connection_main()
    status.assert_called_once()
