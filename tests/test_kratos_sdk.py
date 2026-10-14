from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
import requests

from kratos_agent.brain.config import BrainError
from kratos_agent.sdk import KratosAgent, KratosClient


@pytest.fixture(autouse=True)
def isolated_gateway_environment(tmp_path, monkeypatch):
    """Gateway contract mocks must not inherit the user's selected browser account."""
    from kratos_agent.brain import account_store as accounts_module

    auth_dir = tmp_path / "auth"
    monkeypatch.setenv("KRATOS_AUTH_DIR", str(auth_dir))
    monkeypatch.setattr(accounts_module, "account_store", accounts_module.AccountStore(auth_dir))
    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "gateway")
    for name in ("KRATOS_MODEL", "KRATOS_RUNTIME_MODEL", "KRATOS_RUNTIME_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KRATOS_BASE_URL", "http://127.0.0.1:20128/v1")
    monkeypatch.setenv("KRATOS_CHAT_ENDPOINT", "http://127.0.0.1:20128/v1/chat/completions")
    monkeypatch.setenv("KRATOS_API_KEY", "sdk-contract-test-key")
    monkeypatch.setenv("KRATOS_CATALOG_CACHE_PATH", str(tmp_path / "catalog.json"))


def _json_response(body: dict, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode("utf-8")
    response.url = "http://127.0.0.1:20128/v1/chat/completions"
    return response


def _completion_body(*, content: str = "done", tool_calls: list[dict] | None = None) -> dict:
    return {
        "choices": [{
            "message": {"role": "assistant", "content": content, "tool_calls": tool_calls or []},
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }


def test_json_completion_parses_structured_calls_and_uses_only_gateway(monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")
    client = KratosClient(api_key="test-key", max_retries=0)
    posted = Mock(return_value=_json_response(_completion_body(
        content="",
        tool_calls=[{
            "id": "call-1",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"file_path":"src/main.py"}'},
        }],
    )))
    client.session.post = posted

    result = client.complete({"model": "kratos-reasoning-v1", "messages": [], "stream": False})

    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"file_path": "src/main.py"}
    assert result.usage["total_tokens"] == 16
    assert client.session.trust_env is False
    assert posted.call_args.args[0] == "http://127.0.0.1:20128/v1/chat/completions"
    assert posted.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_streaming_accumulates_fragmented_text_and_tool_arguments(monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")

    class StreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def iter_lines(self, decode_unicode=False):
            events = [
                {"choices": [{"delta": {"content": "Checking "}}]},
                {"choices": [{"delta": {"content": "the file."}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-7", "function": {"name": "read_file", "arguments": '{"file_path":'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"README.md"}'}}]}, "finish_reason": "tool_calls"}]},
                "[DONE]",
            ]
            for event in events:
                value = event if isinstance(event, str) else json.dumps(event)
                yield f"data: {value}".encode("utf-8")

    client = KratosClient(max_retries=0)
    client.session.post = Mock(return_value=StreamResponse())
    chunks: list[str] = []

    result = client.complete(
        {"model": "kratos-reasoning-v1", "messages": [], "stream": True},
        on_chunk=chunks.append,
    )

    assert result.text == "Checking the file."
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}
    assert "".join(chunks) == result.text


def test_malformed_tool_arguments_fail_closed(monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")
    client = KratosClient(max_retries=0)
    client.session.post = Mock(return_value=_json_response(_completion_body(
        content="",
        tool_calls=[{"id": "bad", "type": "function", "function": {"name": "run", "arguments": "[]"}}],
    )))

    with pytest.raises(BrainError, match="JSON object"):
        client.complete({"model": "kratos-reasoning-v1", "messages": [], "stream": False})


def test_unconfigured_or_different_model_fails_without_network(monkeypatch):
    monkeypatch.delenv("KRATOS_MODEL", raising=False)
    monkeypatch.delenv("KRATOS_RUNTIME_MODEL", raising=False)
    client = KratosClient(max_retries=0)
    client.session.post = Mock(side_effect=AssertionError("must not reach gateway"))

    with pytest.raises(BrainError, match="Set KRATOS_MODEL"):
        client.complete({"model": "unconfigured-model", "messages": [], "stream": False})

    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")
    with pytest.raises(BrainError, match="locked to KRATOS_MODEL"):
        client.complete({"model": "another-model", "messages": [], "stream": False})
    client.session.post.assert_not_called()


def test_transient_gateway_error_retries_same_kratos_endpoint(monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")
    client = KratosClient(max_retries=1)
    posted = Mock(side_effect=[
        _json_response({"error": {"message": "temporarily unavailable"}}, status=503),
        _json_response(_completion_body()),
    ])
    client.session.post = posted
    monkeypatch.setattr("kratos_agent.sdk.client.time.sleep", lambda _seconds: None)

    result = client.complete({"model": "kratos-reasoning-v1", "messages": [], "stream": False})

    assert result.text == "done"
    assert posted.call_count == 2
    assert {call.args[0] for call in posted.call_args_list} == {client.endpoint_url}
    assert {call.kwargs["json"]["model"] for call in posted.call_args_list} == {"kratos-reasoning-v1"}


def test_agent_facade_uses_injected_runtime_and_registers_tools(monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")

    class Registry:
        def __init__(self):
            self.registered = []

        def register(self, spec, handler):
            self.registered.append((spec, handler))

        def specs(self):
            return [item[0] for item in self.registered]

    class Runtime:
        def __init__(self):
            self.tools_registry = Registry()
            self.tools = []
            self.loop = type("Loop", (), {})()

        def run_agent(self, prompt):
            return f"ran: {prompt}"

        def run_chat_restricted(self, prompt):
            return f"chat: {prompt}"

    runtime = Runtime()
    agent = KratosAgent(runtime=runtime)
    spec = agent.register_tool("echo", "Return input", {"type": "object", "properties": {}}, lambda: "ok")

    assert agent.run("inspect this") == "ran: inspect this"
    assert agent.run_chat("hello") == "chat: hello"
    assert runtime.tools == [spec]
