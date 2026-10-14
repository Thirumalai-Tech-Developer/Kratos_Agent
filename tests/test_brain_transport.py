from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from kratos_agent.brain.brain import get_agent_response
from kratos_agent.brain.tool_calls import extract_tool_calls_from_text
from kratos_agent.brain.client import BrainClient
from kratos_agent.brain.config import (
    DEFAULT_CHAT_ENDPOINT,
    BrainBadRequestError,
    BrainConnectionError,
    BrainError,
    get_model,
)


@pytest.fixture(autouse=True)
def kratos_model_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KRATOS_CATALOG_CACHE_PATH", str(tmp_path / "catalog.json"))
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")
    monkeypatch.setenv("KRATOS_RUNTIME_MODEL", "kratos-reasoning-v1")
    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "gateway")


def _response(body: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = json.dumps(body)
    response.iter_lines.return_value = []
    response.__enter__.return_value = response
    return response


def test_build_request_contains_configured_kratos_model_and_messages():
    client = BrainClient(endpoint_url=DEFAULT_CHAT_ENDPOINT)
    envelope = client.build_envelope(
        "kratos-reasoning-v1",
        [{"role": "user", "content": "hello"}],
        system_instruction="system test",
        stream=True,
    )

    assert envelope["model"] == "kratos-reasoning-v1"
    assert envelope["stream"] is True
    assert envelope["messages"] == [
        {"role": "system", "content": "system test"},
        {"role": "user", "content": "hello"},
    ]
    assert client.session.trust_env is False


@patch("requests.Session.post")
def test_streaming_sse_success(mock_post):
    response = _response({})
    response.iter_lines.return_value = [
        'data: {"choices": [{"delta": {"content": "Hello "}}]}',
        'data: {"choices": [{"delta": {"content": "Kratos!"}}]}',
        "data: [DONE]",
    ]
    mock_post.return_value = response

    result = BrainClient().generate("kratos-reasoning-v1", [{"role": "user", "content": "hi"}])
    assert result == "Hello Kratos!"


@patch("requests.Session.post")
def test_empty_stream_retries_same_model_as_json(mock_post):
    empty_sse = _response({})
    empty_sse.iter_lines.return_value = []
    json_response = _response({"choices": [{"message": {"content": "Recovered answer"}}]})
    mock_post.side_effect = [empty_sse, json_response]

    result = BrainClient().generate(
        "kratos-reasoning-v1", [{"role": "user", "content": "inspect the workspace"}], max_retries=0
    )

    assert result == "Recovered answer"
    assert mock_post.call_count == 2
    assert {call.kwargs["json"]["model"] for call in mock_post.call_args_list} == {"kratos-reasoning-v1"}


@pytest.mark.parametrize('stream', [True, False])
@patch('requests.Session.post')
def test_repetitive_response_stops_before_callback_and_does_not_retry(mock_post, stream):
    from kratos_agent.core.model_guard import RepetitiveOutputError
    response = _response({'choices': [{'message': {'content': 'WebGL 2.0 (' * 80}}]})
    response.iter_lines.return_value = [
        'data: ' + json.dumps({'choices': [{'delta': {'content': 'WebGL 2.0 (' * 80}}]}),
        'data: [DONE]',
    ]
    mock_post.return_value = response
    chunks = []
    with pytest.raises(RepetitiveOutputError):
        BrainClient().complete('kratos-reasoning-v1', [{'role': 'user', 'content': 'check'}], stream=stream, on_chunk=chunks.append)
    assert not chunks
    assert mock_post.call_count == 1
    response.close.assert_called_once()


@patch("requests.Session.post")
def test_structured_tool_calls_are_preserved_by_compatibility_client(mock_post):
    mock_post.return_value = _response({
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "run_terminal_command", "arguments": '{"command":"pwd"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }]
    })

    result = BrainClient().generate(
        "kratos-reasoning-v1", [{"role": "user", "content": "inspect the workspace"}], stream=False
    )

    assert result.startswith("call:run_terminal_command")
    assert '"pwd"' in result


@patch("requests.Session.post")
def test_gateway_errors_are_visible_and_not_retried(mock_post):
    response = _response({"error": {"message": "invalid model parameter"}}, status=400)
    mock_post.return_value = response

    with pytest.raises(BrainBadRequestError, match="Invalid Kratos model request"):
        BrainClient().generate("kratos-reasoning-v1", [{"role": "user", "content": "hi"}], max_retries=2)
    assert mock_post.call_count == 1


@patch("requests.Session.post", side_effect=requests.exceptions.ConnectionError("Connection refused"))
def test_gateway_outage_is_reported_without_fallback(mock_post):
    with pytest.raises(BrainConnectionError, match="Kratos model gateway is unreachable"):
        BrainClient().generate("kratos-reasoning-v1", [{"role": "user", "content": "hi"}], max_retries=0)
    assert mock_post.call_count == 1


@patch("requests.Session.get")
def test_model_catalog_filters_everything_except_configured_kratos_id(mock_get):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": [{"id": "kratos-reasoning-v1"}, {"id": "claude-model"}]}
    mock_get.return_value = response

    assert get_model(endpoint="http://127.0.0.1:20128/v1/models", refresh=True) == ["kratos-reasoning-v1"]


def test_get_agent_response_uses_compatibility_client(monkeypatch):
    monkeypatch.setattr(BrainClient, "generate", lambda _self, **_kwargs: "Hello from Kratos")
    assert get_agent_response("Hi there") == "Hello from Kratos"


def test_tool_calling_extraction_from_coding_output():
    raw_text = 'call:write_file{file_path: "index.html", content: "<h1>Kratos</h1>"}'
    text, tool_calls = extract_tool_calls_from_text(raw_text)
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "write_file"
    assert tool_calls[0]["args"]["file_path"] == "index.html"
    assert "Kratos" in tool_calls[0]["args"]["content"]


def _sse_events(*events):
    response = _response({})
    response.iter_lines.return_value = ['data: ' + json.dumps(event) for event in events]
    return response


@patch('kratos_agent.sdk.client._retry_wait')
@patch('requests.Session.post')
def test_transient_gateway_sse_error_retries_the_same_model(mock_post, _wait):
    from kratos_agent.sdk.client import KratosClient
    failed = _sse_events({'error': {'status': 503, 'message': 'private upstream error'}})
    recovered = _sse_events({'choices': [{'delta': {'content': 'Recovered'}, 'finish_reason': 'stop'}]})
    mock_post.side_effect = [failed, recovered]
    client = KratosClient(provider='gateway', configured_model='kratos-reasoning-v1', max_retries=1)
    result = client.complete({'model': 'kratos-reasoning-v1', 'messages': [{'role': 'user', 'content': 'hello'}]})
    assert result.text == 'Recovered'
    assert mock_post.call_count == 2
    assert {call.kwargs['json']['model'] for call in mock_post.call_args_list} == {'kratos-reasoning-v1'}
    failed.close.assert_called_once()


@patch('requests.Session.post')
def test_gateway_sse_only_failure_recovers_as_json_without_changing_model(mock_post):
    from kratos_agent.sdk.client import KratosClient
    mock_post.side_effect = [_sse_events({'error': {'message': 'stream-only transport failure'}}),
                             _response({'choices': [{'message': {'content': 'Recovered as JSON'}}]})]
    chunks = []
    client = KratosClient(provider='gateway', configured_model='kratos-reasoning-v1', max_retries=0)
    result = client.complete({'model': 'kratos-reasoning-v1', 'messages': []}, on_chunk=chunks.append)
    assert result.text == 'Recovered as JSON'
    assert chunks == ['Recovered as JSON']
    assert [call.kwargs['json']['stream'] for call in mock_post.call_args_list] == [True, False]


@patch('requests.Session.post')
def test_gateway_sse_login_failure_does_not_retry_or_expose_upstream_details(mock_post):
    from kratos_agent.sdk.client import KratosClient, KratosStreamError
    mock_post.return_value = _sse_events({'error': {'code': 401, 'message': 'private-token-value'}})
    client = KratosClient(provider='gateway', configured_model='kratos-reasoning-v1', max_retries=2)
    with pytest.raises(KratosStreamError, match='valid login') as error:
        client.complete({'model': 'kratos-reasoning-v1', 'messages': []})
    assert 'private-token-value' not in str(error.value)
    assert mock_post.call_count == 1


@pytest.mark.parametrize('native_tool', [False, True])
@patch('requests.Session.post')
def test_gateway_partial_sse_failure_is_never_replayed(mock_post, native_tool):
    from kratos_agent.sdk.client import KratosClient, KratosStreamError
    from kratos_agent.brain.config import BrainToolCallError
    delta = {'tool_calls': [{'index': 0, 'id': 'one', 'function': {'name': 'write_file', 'arguments': '{'}}]} if native_tool else {'content': 'partial answer'}
    mock_post.return_value = _sse_events({'choices': [{'delta': delta}]}, {'error': {'status': 502}})
    client = KratosClient(provider='gateway', configured_model='kratos-reasoning-v1', max_retries=2)
    with pytest.raises(BrainToolCallError if native_tool else KratosStreamError):
        client.complete({'model': 'kratos-reasoning-v1', 'messages': []})
    assert mock_post.call_count == 1


@patch('kratos_agent.sdk.client._retry_wait')
@patch('requests.Session.post')
def test_gateway_rate_limited_sse_has_bounded_retries_and_clear_status(mock_post, _wait):
    from kratos_agent.sdk.client import KratosClient, KratosStreamError
    mock_post.return_value = _sse_events({'error': {'code': 'rate_limit_exceeded'}})
    client = KratosClient(provider='gateway', configured_model='kratos-reasoning-v1', max_retries=2)
    with pytest.raises(KratosStreamError, match='HTTP 429'):
        client.complete({'model': 'kratos-reasoning-v1', 'messages': []})
    assert mock_post.call_count == 3
