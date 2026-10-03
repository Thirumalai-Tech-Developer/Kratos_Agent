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
def kratos_model_env(monkeypatch):
    monkeypatch.setenv("KRATOS_MODEL", "kratos-reasoning-v1")


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
    if stream:
        response.__exit__.assert_called_once()


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
