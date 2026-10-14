from kratos_agent.brain.browser_conversation import prepare_conversation, completed_cursor, conversation_key
from kratos_agent.sdk.client import KratosCompletion, KratosToolCall


def test_setup_once_followup_sends_only_new_messages_and_tools_results():
    initial = {"model": "chatgpt-web/thinking", "messages": [{"role": "system", "content": "instructions"}, {"role": "user", "content": "inspect"}], "tools": [{"function": {"name": "read_file"}}]}
    outgoing, cursor, continuing, include_tools = prepare_conversation(initial)
    assert not continuing and include_tools and outgoing == initial
    completion = KratosCompletion("", [KratosToolCall("local-id", "read_file", {"path": "a.py"})])
    previous = completed_cursor(cursor, {"conversation": {"tab_id": 5, "url": "https://chatgpt.com/c/owned"}}, completion)
    initial["messages"].extend([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "another-id", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}]},
        {"role": "tool", "content": "first result", "tool_call_id": "another-id"},
        {"role": "tool", "content": "second result", "tool_call_id": "other-id"},
    ])
    initial["messages"][0]["content"] += " runtime state changed"
    outgoing, _, continuing, include_tools = prepare_conversation(initial, previous)
    assert continuing and not include_tools
    assert [m["content"] for m in outgoing["messages"]] == ["first result", "second result"]
    assert "instructions" not in str(previous)


def test_compaction_bootstraps_fresh_conversation_and_tool_changes_are_updates():
    first = {"model": "web/model", "messages": [{"role": "system", "content": "setup"}, {"role": "user", "content": "first"}]}
    _, cursor, _, _ = prepare_conversation(first)
    old = completed_cursor(cursor, {"conversation": {"native": {"id": "remote"}}}, KratosCompletion("answer"))
    changed = {**first, "messages": [*first["messages"], {"role": "assistant", "content": "answer"}, {"role": "user", "content": "next"}], "tools": [{"function": {"name": "second_tool"}}]}
    outgoing, _, continuing, tools = prepare_conversation(changed, old)
    assert continuing and tools and outgoing["messages"] == [{"role": "user", "content": "next"}]
    compacted = {**first, "messages": [{"role": "system", "content": "setup"}, {"role": "user", "content": "summary"}, {"role": "user", "content": "next"}]}
    outgoing, _, continuing, tools = prepare_conversation(compacted, old)
    assert not continuing and tools and outgoing == compacted
    assert conversation_key("account", "one", "m") != conversation_key("account", "two", "m")
    assert conversation_key("account", "one", "m") != conversation_key("other-account", "one", "m")


def test_rejected_reply_keeps_cursor_so_correction_can_continue_without_replay():
    payload = {"model": "web/model", "messages": [{"role": "user", "content": "inspect"}]}
    _, cursor, _, _ = prepare_conversation(payload)
    previous = completed_cursor(cursor, {"conversation": {"native": {"id": "remote"}}})
    payload["messages"].append({"role": "user", "content": "correct the format"})
    outgoing, _, continuing, _ = prepare_conversation(payload, previous)
    assert continuing and outgoing["messages"] == [{"role": "user", "content": "correct the format"}]


def test_speech_metadata_does_not_replay_the_previous_answer_on_continuation():
    first = {"model": "web/model", "messages": [{"role": "system", "content": "setup"}, {"role": "user", "content": "hi"}]}
    _, cursor, _, _ = prepare_conversation(first)
    previous = completed_cursor(cursor, {"conversation": {"native": {"id": "saved"}}}, KratosCompletion("Hey! I'm here and ready to help. [[speak]]Hi! I'm ready.[[/speak]]"))
    next_payload = {**first, "messages": [*first["messages"], {"role": "assistant", "content": "Hey! I'm here and ready to help."}, {"role": "user", "content": "continue"}]}
    outgoing, _, continuing, include_tools = prepare_conversation(next_payload, previous)
    assert continuing and not include_tools
    assert outgoing["messages"] == [{"role": "user", "content": "continue"}]
