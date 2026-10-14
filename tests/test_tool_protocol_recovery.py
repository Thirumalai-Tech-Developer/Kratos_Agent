"""A different wire protocol still requires complete, registered tool arguments."""
from copy import deepcopy
import json

import pytest

from kratos_agent.brain.config import BrainToolCallError
from kratos_agent.brain.browser_conversation import prepare_conversation
from kratos_agent.core.context_pipeline import ContextBudget, ContextBuilder
from kratos_agent.core.model_adapter import KratosModelAdapter, tool_recovery_instruction
from kratos_agent.core.runtime_contracts import ChatMessage


TOOLS = [{"type": "function", "function": {
    "name": "read_file",
    "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}},
                   "required": ["file_path"], "additionalProperties": False},
}}]


class RecordingClient:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs.get("on_chunk"):
            kwargs["on_chunk"]("RAW PROTOCOL SHOULD NOT REACH DISPLAY")
        return self.result


def request(protocol="json"):
    return {
        "system": "The original task instructions.",
        "messages": [
            {"role": "user", "content": "inspect the project"},
            {"role": "user", "content": tool_recovery_instruction(protocol, TOOLS)},
        ],
        "tools": deepcopy(TOOLS),
        "tool_recovery_protocol": protocol,
    }


def envelope(calls, text=""):
    return json.dumps({"text": text, "tool_calls": calls})


def test_api_recovery_changes_wire_protocol_without_changing_model_or_system():
    client = RecordingClient((envelope([{"name": "read_file", "arguments": {"file_path": "README.md"}}]), []))
    adapter = KratosModelAdapter("provider/existing-model", client)
    original = request()
    before = deepcopy(original)
    chunks = []
    response = adapter.complete(original, on_chunk=chunks.append)
    sent = client.requests[0]
    assert sent["model"] == adapter.model
    assert sent["tools"] == []
    assert sent["on_chunk"] is None
    assert sent["messages"] == original["messages"]
    assert sent["system_instruction"] == original["system"] + adapter._tool_protocol_hint() + "\n\n" + tool_recovery_instruction("json", TOOLS)
    assert response.tool_calls[0].arguments == {"file_path": "README.md"}
    assert chunks == []
    assert original == before


def test_api_recovery_restores_current_schema_after_compaction_omits_correction():
    correction = tool_recovery_instruction("single_json", TOOLS)
    history = [
        ChatMessage("user", "Original task " + "x" * 1000),
        ChatMessage("user", correction),
        ChatMessage("assistant", "Earlier observed result " + "y" * 4000),
        ChatMessage("user", "[Recovery required for task]: File missing. Choose a fallback."),
    ]
    context = ContextBuilder(ContextBudget(max_input_tokens=1000, reserve_output_tokens=10))
    compacted, detail = context.compact_history(history, force=True)
    assert detail is not None
    assert not any(correction in message.content for message in compacted)
    assert not any('"parameters"' in message.content for message in compacted)
    original = request("single_json")
    original["messages"] = [message.to_dict() for message in compacted]
    client = RecordingClient((envelope([{"name": "read_file", "arguments": {"file_path": "README.md"}}]), []))
    response = KratosModelAdapter("provider/model", client).complete(original)
    sent = client.requests[0]
    assert sent["tools"] == []
    assert correction in sent["system_instruction"]
    assert sent["messages"] == [{"role": message.role, "content": message.content} for message in compacted]
    assert response.tool_calls[0].arguments == {"file_path": "README.md"}


@pytest.mark.parametrize("call", [
    {"name": "not_registered", "arguments": {"file_path": "README.md"}},
    {"name": "read_file", "arguments": {}},
    {"name": "read_file", "arguments": {"file_path": 7}},
    {"name": "read_file", "arguments": {"file_path": "README.md", "guessed": True}},
    {"name": "read_file", "arguments": "README.md"},
])
def test_recovery_never_accepts_unregistered_or_schema_invalid_calls(call):
    client = RecordingClient((envelope([call], "should not be displayed"), []))
    chunks = []
    with pytest.raises(BrainToolCallError):
        KratosModelAdapter("provider/model", client).complete(request(), on_chunk=chunks.append)
    assert chunks == []


@pytest.mark.parametrize("protocol", ["single_json", "fresh_plan"])
def test_one_action_modes_reject_a_batch_before_any_execution(protocol):
    calls = [{"name": "read_file", "arguments": {"file_path": name}} for name in ("README.md", "main.py")]
    with pytest.raises(BrainToolCallError, match="more than one"):
        KratosModelAdapter("provider/model", RecordingClient((envelope(calls), []))).complete(request(protocol))


def test_recovery_forwards_only_validated_answer_once():
    client = RecordingClient((envelope([], "Verified answer"), []))
    chunks = []
    response = KratosModelAdapter("provider/model", client).complete(request(), on_chunk=chunks.append)
    assert response.text == "Verified answer"
    assert response.tool_calls == []
    assert chunks == ["Verified answer"]


def test_browser_recovery_preserves_cursor_prefix_and_original_native_metadata():
    native = [{"id": "actual-call", "name": "read_file", "args": {"file_path": "README.md"}}]
    client = RecordingClient(("", native))
    adapter = KratosModelAdapter("deepseek-web/deepseek-v4-pro", client)
    original = request("single_json")
    prior_payload = {"messages": original["messages"][:-1], "tools": TOOLS}
    _, previous, _, _ = prepare_conversation(prior_payload)
    previous["remote"] = {"conversation_id": "actual-remote-id"}
    response = adapter.complete(original)
    sent = client.requests[0]
    assert sent["tools"] == TOOLS
    assert sent["messages"] == original["messages"]
    outgoing, _, continuing, include_tools = prepare_conversation(sent, previous)
    assert continuing is True
    assert include_tools is False
    assert outgoing["messages"] == [original["messages"][-1]]
    assert response.tool_calls[0].name == "read_file"


def test_fallback_retains_completed_tool_evidence_without_native_tool_roles():
    original = request()
    original["messages"].insert(1, {"role": "assistant", "content": None, "tool_calls": [
        {"name": "read_file", "arguments": {"file_path": "README.md"}, "call_id": "saved-call"}]})
    original["messages"].insert(2, {"role": "tool", "content": "Real saved file contents",
                                    "tool_call_id": "saved-call", "name": "read_file"})
    client = RecordingClient((envelope([], "Done"), []))
    KratosModelAdapter("provider/model", client).complete(original)
    sent = client.requests[0]["messages"]
    assert len(sent) == len(original["messages"])
    assert "Previously requested local tools" in sent[1]["content"]
    assert "saved-call" in sent[2]["content"]
    assert "Real saved file contents" in sent[2]["content"]
    assert sent[2]["role"] == "user"
    assert not any(item.get("tool_calls") or item["role"] == "tool" for item in sent)


def test_nonfinite_native_json_arguments_are_not_forwarded():
    client = RecordingClient(("", [{"name": "read_file", "args": {"file_path": float("nan")}}]))
    with pytest.raises(BrainToolCallError, match="valid JSON"):
        KratosModelAdapter("provider/model", client).complete(request())


def test_valid_native_call_with_malformed_text_does_not_execute_any_call():
    client = RecordingClient(('call:read_file{"file_path":', [
        {"name": "read_file", "args": {"file_path": "README.md"}}]))
    with pytest.raises(BrainToolCallError):
        KratosModelAdapter("provider/model", client).complete(request())


def test_no_advertised_tools_accepts_only_a_final_envelope():
    original = request()
    original["tools"] = []
    client = RecordingClient((envelope([], "Saved work verified"), []))
    assert KratosModelAdapter("provider/model", client).complete(original).text == "Saved work verified"
    client.result = envelope([{"name": "read_file", "arguments": {"file_path": "README.md"}}]), []
    with pytest.raises(BrainToolCallError):
        KratosModelAdapter("provider/model", client).complete(original)


@pytest.mark.parametrize("calls", [None, {}, ""])
def test_invalid_native_call_collection_rejects_otherwise_valid_json(calls):
    client = RecordingClient((envelope([{"name": "read_file", "arguments": {"file_path": "README.md"}}]), calls))
    with pytest.raises(BrainToolCallError, match="collection"):
        KratosModelAdapter("provider/model", client).complete(request())
