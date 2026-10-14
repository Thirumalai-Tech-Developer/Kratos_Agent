import threading
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.model_adapter import KratosModelAdapter
from kratos_agent.core.runtime_contracts import ChatMessage, EventKind, ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.brain.client import BrainClient
from kratos_agent.brain.config import BrainToolCallError


BROKEN = '<|DSML|calls><|DSML|invoke name="read_file"><|DSML|parameter name="file_path" string="true">'
VALID = 'call:read_file{"file_path":"README.md"}'


@pytest.fixture(autouse=True)
def isolated_model_configuration(monkeypatch):
    # SDK fixtures must not inherit the developer's saved browser selection.
    monkeypatch.setenv("KRATOS_RUNTIME_MODEL", "configured")
    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "gateway")


class SequenceClient:
    def __init__(self, responses, calls):
        self.responses = iter(responses)
        self.requests = []
        self.tool_calls = calls
        self.cancel = None

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) <= 2:
            assert self.tool_calls == [], "A rejected response executed a tool before correction."
        if self.cancel:
            self.cancel.set()
        return next(self.responses)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("KRATOS_MAX_RETRIES", "2")
    monkeypatch.setattr("kratos_agent.core.agent_loop.formulate_agent_plan", lambda **kwargs: None)
    calls, events = [], []
    tools = ToolRegistry()
    tools.register(ToolSpec(name="read_file", description="Read a file", permission=ToolPermission.READ,
                            parameters={"type": "object", "properties": {"file_path": {"type": "string"}},
                                        "required": ["file_path"], "additionalProperties": False}),
                   lambda file_path: calls.append(file_path) or "verified file content")
    def create(responses, cancellation=None):
        client = SequenceClient(responses, calls)
        model = KratosModelAdapter("configured", client)
        loop = AgentLoop(context=ContextBuilder(), instructions=SimpleNamespace(build=lambda: []),
                         tools=tools, model=model, emit=events.append, workspace=tmp_path,
                         cancellation_flag=cancellation)
        return loop, client
    return create, calls, events


def run(loop):
    return loop.run([ChatMessage(role="user", content="Please read README.md")],
                    allow_tool=lambda *args: (True, "allowed"), max_steps=6)


def test_malformed_response_gets_corrected_before_any_tool_executes(setup):
    create, calls, events = setup
    loop, client = create([(BROKEN, []), (VALID, []), ("Verified file content.", [])])
    answer, history = run(loop)
    assert answer == "Verified file content."
    assert calls == ["README.md"]
    assert len(client.requests) == 3
    correction = client.requests[1]["messages"][-1]["content"]
    assert "no" in correction.lower() and "executed" in correction.lower()
    assert BROKEN not in str(client.requests[1])
    assert len([event for event in events if event.kind == EventKind.TOOL_CALL_STARTED]) == 1
    assert not any(event.kind == EventKind.TURN_FAILED for event in events)
    assert sum(message.role == "tool" for message in history) == 1


def test_explicit_bounded_recovery_can_still_stop_after_two_corrections(setup, monkeypatch):
    monkeypatch.setenv("KRATOS_AUTONOMOUS_RECOVERY", "0")
    create, calls, events = setup
    loop, client = create([(BROKEN, [])] * 4)
    answer, history = run(loop)
    assert answer.startswith("Model request failed:")
    assert "2 correction attempts" in answer
    assert len(client.requests) == 3
    assert calls == [] and not any(message.role == "tool" for message in history)
    assert len([event for event in events if event.kind == EventKind.TURN_FAILED]) == 1


def test_mixed_valid_and_malformed_batch_is_rejected_as_a_whole(setup):
    create, calls, events = setup
    first = ("", [{"name": "read_file", "args": {"file_path": "wrong.md"}},
                   {"name": "read_file", "args": ["wrong.md"]}])
    loop, client = create([first, (VALID, []), ("Verified file content.", [])])
    assert run(loop)[0] == "Verified file content."
    assert calls == ["README.md"]


@pytest.mark.parametrize("wrapper", [
    '<tool>{payload}</tool>',
    '<tool_call>{payload}</tool_call>',
    '```json\n{payload}\n```',
    '{payload}',
])
@pytest.mark.parametrize("invalid_arguments", [[], False, 0, None])
def test_falsey_non_object_arguments_cannot_execute_zero_argument_tool(setup, wrapper, invalid_arguments):
    create, calls, events = setup
    malformed = wrapper.format(payload=json.dumps({"name": "zero_arg_tool", "arguments": invalid_arguments}))
    loop, client = create([(malformed, []), ("", [{"name": "zero_arg_tool", "args": {}}]),
                           ("Verified zero-argument tool result.", [])])
    loop.tools.register(ToolSpec(name="zero_arg_tool", description="A zero-argument tool",
                                permission=ToolPermission.READ,
                                parameters={"type": "object", "properties": {}, "additionalProperties": False}),
                        lambda: calls.append("zero_arg_tool") or "verified result")
    assert run(loop)[0] == "Verified zero-argument tool result."
    assert calls == ["zero_arg_tool"]
    assert "RUNTIME TOOL-CALL FORMAT CORRECTION" in client.requests[1]["messages"][-1]["content"]
    assert len([event for event in events if event.kind == EventKind.TOOL_CALL_STARTED]) == 1


def test_unknown_tool_does_not_execute_and_is_corrected(setup):
    create, calls, events = setup
    loop, client = create([("", [{"name": "invented_tool", "args": {}}]),
                           (VALID, []), ("Verified file content.", [])])
    assert run(loop)[0] == "Verified file content."
    assert calls == ["README.md"]
    assert not any(event.payload.get("name") == "invented_tool" for event in events
                   if event.kind == EventKind.TOOL_CALL_STARTED)


def test_cancel_during_invalid_response_prevents_recovery_request(setup):
    create, calls, events = setup
    cancellation = threading.Event()
    loop, client = create([(BROKEN, []), (VALID, [])], cancellation)
    client.cancel = cancellation
    answer, history = run(loop)
    assert "interrupted" in answer.lower()
    assert len(client.requests) == 1 and calls == []
    assert any(event.kind == EventKind.TURN_FAILED and event.payload.get("error") == "cancelled"
               for event in events)


@pytest.mark.parametrize("text", [
    'call:read_file{file_path:"README.md"}',
    'call:read_file{"file_path":"README.md"',
    '<tool>{"name":"read_file","arguments":[]}</tool>',
    VALID + '\ncall:read_file{"file_path":',
    '<|DSML|calls><|DSML|invoke name="read_file">'
    '<|DSML|parameter name="file_path" string="true">README.md</|DSML|parameter>'
    '<|DSML|parameter name="other">unterminated</|DSML|invoke></|DSML|calls>',
])
def test_incomplete_or_guessed_text_calls_are_rejected_before_execution(setup, text):
    create, calls, events = setup
    loop, client = create([(text, []), (VALID, []), ("Verified file content.", [])])
    assert run(loop)[0] == "Verified file content."
    assert calls == ["README.md"]


def test_tool_format_recovery_can_be_disabled(setup, monkeypatch):
    monkeypatch.setenv("KRATOS_AUTONOMOUS_RECOVERY", "0")
    monkeypatch.setenv("KRATOS_MAX_RETRIES", "0")
    create, calls, events = setup
    loop, client = create([(BROKEN, []), (VALID, [])])
    assert "0 correction attempts" in run(loop)[0]
    assert len(client.requests) == 1 and calls == []


def test_format_recovery_preserves_tool_permission_gate(setup):
    create, calls, events = setup
    loop, client = create([(BROKEN, []), (VALID, []), ("File access was denied.", [])])
    answer, history = loop.run([ChatMessage(role="user", content="Please read README.md")],
                               allow_tool=lambda *args: (False, "Access denied"), max_steps=6)
    assert answer == "File access was denied." and calls == []
    assert any(message.role == "tool" and "denied" in message.content.lower() for message in history)


class Stream:
    status_code = 200

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_lines(self, **_):
        for event in self.events:
            yield ("data: " + json.dumps(event)).encode()


@pytest.mark.parametrize("incomplete", [False, True])
def test_sdk_stream_error_is_corrected_by_loop_before_execution(setup, monkeypatch, incomplete):
    monkeypatch.setenv("KRATOS_MODEL", "configured")
    create, calls, events = setup
    loop, _ = create([])
    brain = BrainClient("http://127.0.0.1:1/v1/chat/completions")
    first_choice = {"delta": {"tool_calls": [{"index": 0, "function": {
        "name": "read_file", "arguments": '{"file_path":"wrong.md"}' if incomplete else '{"file_path":'}}]}}
    if not incomplete:
        first_choice["finish_reason"] = "tool_calls"
    streams = iter([
        Stream([{"choices": [first_choice]}]),
        Stream([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "valid-call", "function": {
            "name": "read_file", "arguments": '{"file_path":"README.md"}'}}]}, "finish_reason": "tool_calls"}]}]),
        Stream([{"choices": [{"delta": {"content": "Verified file content."}, "finish_reason": "stop"}]}]),
    ])
    def post(*args, **kwargs):
        if brain.session.post.call_count <= 2:
            assert calls == []
        return next(streams)
    brain.session.post = Mock(side_effect=post)
    loop.model = KratosModelAdapter("configured", brain)
    try:
        assert run(loop)[0] == "Verified file content."
        assert brain.session.post.call_count == 3 and calls == ["README.md"]
    finally:
        brain.session.close()


@pytest.mark.parametrize("delta", [
    {"tool_calls": ["not a call"]},
    {"tool_calls": [{"index": "invalid", "function": {}}]},
    {"tool_calls": [{"index": 0, "function": "wrong"}]},
])
def test_malformed_native_stream_delta_is_a_recoverable_error(monkeypatch, delta):
    monkeypatch.setenv("KRATOS_MODEL", "configured")
    brain = BrainClient("http://127.0.0.1:1/v1/chat/completions")
    brain.session.post = Mock(return_value=Stream([{"choices": [{"delta": delta, "finish_reason": "tool_calls"}]}]))
    try:
        with pytest.raises(BrainToolCallError):
            brain.complete("configured", [])
        assert brain.session.post.call_count == 1
    finally:
        brain.session.close()


def test_format_recovery_continues_after_two_corrections_and_changes_method(setup):
    create, calls, events = setup
    loop, client = create([(BROKEN, [])] * 4 + [(VALID, []), ("Verified file content.", [])])
    loop.cancellation_flag.wait = Mock(return_value=False)
    answer, history = run(loop)
    assert answer == "Verified file content."
    assert calls == ["README.md"] and len(client.requests) == 6
    retries = [event for event in events if event.kind == EventKind.RETRY]
    assert [event.payload["strategy"] for event in retries] == ["schema_correction", "schema_correction", "json", "json"]
    assert all(event.payload["recoverable"] for event in retries)
    assert client.requests[3]["tools"] == []  # Alternate API protocol omits native tools.
    assert not any(event.kind == EventKind.TURN_FAILED for event in events)
    assert not any("Invalid tool response rejected" in event.payload.get("chunk", "") for event in events)
    assert any("alternate local JSON response protocol" in message.content for message in history)


def test_all_recovery_methods_can_be_tried_before_a_valid_response(setup):
    create, calls, events = setup
    loop, client = create([(BROKEN, [])] * 8 + [(VALID, []), ("Verified file content.", [])])
    loop.cancellation_flag.wait = Mock(return_value=False)
    answer, _ = loop.run([ChatMessage(role="user", content="Please read README.md")], allow_tool=lambda *args: (True, "allowed"), max_steps=12)
    assert answer == "Verified file content." and calls == ["README.md"]
    assert len(client.requests) == 10
    strategies = [event.payload["strategy"] for event in events if event.kind == EventKind.RETRY]
    assert strategies == ["schema_correction"] * 2 + ["json"] * 2 + ["single_json"] * 2 + ["fresh_plan"] * 2
    assert not any(event.kind == EventKind.TURN_FAILED for event in events)


def test_stop_during_extended_recovery_prevents_another_model_request(setup):
    create, calls, events = setup
    cancellation = threading.Event()
    loop, client = create([(BROKEN, [])] * 8, cancellation)
    original = loop.emit_fn
    def emit(event):
        original(event)
        if event.kind == EventKind.RETRY and event.payload["attempt"] == 4:
            cancellation.set()
    loop.emit_fn = emit
    answer, _ = run(loop)
    assert "interrupted" in answer.lower()
    assert len(client.requests) == 4 and calls == []
    assert any(event.kind == EventKind.TURN_FAILED and event.payload.get("error") == "cancelled" for event in events)


def test_json_protocol_remains_active_after_valid_tool_and_final_answer(setup):
    create, calls, events = setup
    valid_call = json.dumps({"text": "", "tool_calls": [
        {"name": "read_file", "arguments": {"file_path": "README.md"}}]})
    final = json.dumps({"text": "Verified file content.", "tool_calls": []})
    loop, client = create([(BROKEN, [])] * 3 + [(valid_call, []), (final, [])])
    loop.cancellation_flag.wait = Mock(return_value=False)
    answer, _ = run(loop)
    assert answer == "Verified file content."
    assert calls == ["README.md"] and len(client.requests) == 5
    assert client.requests[-1]["tools"] == []
    displayed = "".join(event.payload.get("chunk", "") for event in events
                        if event.kind == EventKind.MODEL_CHUNK)
    assert "tool_calls" not in displayed and "file_path" not in displayed
    assert not any(event.kind == EventKind.TURN_FAILED for event in events)
