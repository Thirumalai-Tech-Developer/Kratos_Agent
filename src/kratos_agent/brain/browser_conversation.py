"""Cursor for an owned browser conversation; no prompt text is stored here."""
from __future__ import annotations

import hashlib
import json
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def message_digest(message):
    calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or call
        arguments = function.get("arguments", function.get("args", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                pass
        calls.append({"name": function.get("name"), "arguments": arguments})
    content = message.get("content") or ""
    if message.get("role") == "assistant" and isinstance(content, str):
        from kratos_agent.output.speech_directives import extract_speech_directives
        content = extract_speech_directives(content).display_text.strip()
    # Call IDs are local runtime IDs, not provider conversation IDs.
    return digest({"role": message.get("role", "user"),
                   "content": content, "calls": calls})


def prepare_conversation(payload, previous=None):
    messages = [item for item in payload.get("messages", []) if item.get("role") not in {"system", "developer"}]
    hashes = [message_digest(item) for item in messages]
    previous = previous or {}
    prefix = previous.get("messages", [])
    continuing = bool(previous.get("remote") and prefix and hashes[:len(prefix)] == prefix)
    offset = len(prefix) if continuing else 0
    if continuing and offset < len(hashes) and hashes[offset] == previous.get("assistant"):
        offset += 1
    tools_hash = digest([payload.get("tools") or [], payload.get("tool_choice", "auto")])
    outgoing = dict(payload)
    if continuing:
        outgoing["messages"] = messages[offset:]
    # On a fresh conversation bootstrap the current working context. On an
    # append, transmit only new messages; changing tools gets a small update.
    return outgoing, {"messages": hashes, "tools": tools_hash}, continuing, (not continuing or tools_hash != previous.get("tools"))


def completed_cursor(cursor, result, completion=None):
    cursor = dict(cursor, remote=result["conversation"], updated_at=time.time())
    if completion is not None:
        cursor["assistant"] = message_digest({"role": "assistant", "content": completion.text,
            "tool_calls": [{"name": call.name, "arguments": call.arguments} for call in completion.tool_calls]})
    return cursor


def conversation_key(account_id, session_id, model):
    return digest([account_id, session_id, model])
