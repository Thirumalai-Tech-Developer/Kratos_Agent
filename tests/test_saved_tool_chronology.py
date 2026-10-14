"""Executed tool rows and model prose survive real local session persistence."""
import ast
import logging
import re
import threading
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from kratos_agent.core.change_review import ChangeReview, checkpoint_turn
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.d1_client import D1DatabaseClient
from kratos_agent.core.event_bus import event_bus
from kratos_agent.core.event_store import EventStore
from kratos_agent.core.project_memory import ProjectMemory
from kratos_agent.core.runtime_contracts import ChatMessage, EventKind, RuntimeEvent
from kratos_agent.core.subagents import scoped_subagent_event


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    # Use the real composition methods without importing main.py's global
    # runtime or discovering the user's configured providers and MCP servers.
    source = Path(__file__).parents[1] / "src/kratos_agent/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KratosRuntime")
    selected = {
        "_emit", "_record_saved_tool_event", "_finalize_saved_tool_calls", "invoke", "run_agent", "_save_context_checkpoint",
        "_refresh_project_instructions", "_project_instruction_message", "_append_project_instruction_update",
    }
    klass.body = [node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name in selected]
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"_serialize_turn", "_derive_turn_status", "_recent_conversation", "_resumable_plan"}]
    namespace = {
        "Any": Any, "ChatMessage": ChatMessage, "RuntimeEvent": RuntimeEvent, "EventKind": EventKind,
        "threading": threading, "event_bus": event_bus, "checkpoint_turn": checkpoint_turn,
        "wraps": wraps, "re": re,
        "logger": logging.getLogger(__name__),
        "_ACTIONABLE_REQUEST_PATTERN": re.compile(r"\bcreate\b.*\bfile\b", re.IGNORECASE),
    }
    exec(compile(ast.Module(body=[*functions, klass], type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102 - trusted source methods only
    db = D1DatabaseClient(account_id="", database_id="", api_token="", local_db_path=tmp_path / "session.db")
    # Import under explicit offline defaults and prevent any legacy-user-file
    # migration when constructing the isolated session manager.
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "")
    monkeypatch.setenv("CLOUDFLARE_D1_DATABASE_ID", "")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
    from kratos_agent.core import memory as memory_module
    monkeypatch.setattr(memory_module, "LEGACY_MEMORY_FILE", tmp_path / "absent-legacy.json")
    instance = namespace["KratosRuntime"]()
    instance.workspace = tmp_path
    instance.change_review = ChangeReview(tmp_path)
    instance.project_memory = ProjectMemory(tmp_path)
    instance._turn_lock = threading.RLock()
    instance._cancellation_flag = threading.Event()
    instance._history = []
    instance._current_tool_calls = []
    instance.context = ContextBuilder()
    instance.memory = memory_module.AgenticMemory(sessions_dir=tmp_path / "sessions", db=db)
    instance._event_store = EventStore(tmp_path / "events", db=db)
    instance._allow_tool = lambda *_: (True, "allowed")
    instance.loop = SimpleNamespace(current_plan=None, run=None)
    yield instance
    db.close()


def emit(runtime, kind, payload, timestamp=1):
    runtime._emit(RuntimeEvent(kind, payload, "parent-turn", timestamp=timestamp))


def scripted_activity(runtime, history):
    emit(runtime, EventKind.MODEL_RESPONSE, {"display_text": "Inspecting the source.", "usage": {}})
    emit(runtime, EventKind.TOOL_REQUESTED, {"name": "read_file", "call_id": "same-id", "arguments": {"file_path": "app.py"}})
    emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "same-id", "arguments": {"file_path": "app.py"}})
    emit(runtime, EventKind.TOOL_COMPLETED, {"name": "read_file", "call_id": "same-id", "content": "Observed source", "duration_ms": 4})
    emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "list_directory", "call_id": "second", "arguments": {"path": "."}})
    emit(runtime, EventKind.TOOL_COMPLETED, {"name": "list_directory", "call_id": "second", "content": "app.py"})
    emit(runtime, EventKind.MODEL_RESPONSE, {"display_text": "Checking the result.", "usage": {}})
    emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "run_terminal_command", "call_id": "verify", "arguments": {"command": "check app.py"}})
    emit(runtime, EventKind.TOOL_FAILED, {"name": "run_terminal_command", "call_id": "verify", "content": "Check failed", "is_error": True})
    child = {"agent_id": "worker-a", "role": "tester", "task": "Inspect independently"}
    for kind, payload in [
        (EventKind.MODEL_RESPONSE, {"display_text": "Private child prose", "usage": {"input_tokens": 99}}),
        (EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "same-id", "arguments": {"file_path": "child.py"}}),
        (EventKind.TOOL_COMPLETED, {"name": "read_file", "call_id": "same-id", "content": "Child observed source"}),
    ]:
        runtime._emit(scoped_subagent_event(RuntimeEvent(kind, payload, "child-turn"), child, "parent-turn"))
    return "Evidence saved.", [*history, ChatMessage("assistant", "Evidence saved.")]


@pytest.mark.parametrize("method", ["run_agent", "invoke"])
def test_tool_results_and_prose_anchors_survive_database_and_disk_reload(runtime, method):
    runtime.loop.run = lambda history, *_args, **_kwargs: scripted_activity(runtime, history)
    if method == "invoke":
        assert runtime.invoke([{"role": "user", "content": "Inspect source"}]) == "Evidence saved."
    else:
        assert runtime.run_agent("Inspect source") == "Evidence saved."
    session_id = runtime.memory.active_session.session_id
    saved = runtime.memory.active_session.turns[-1]["tools_used"]
    assert len(saved) == 4
    assert [row["call_id"] for row in saved] == ["same-id", "second", "verify", "subagent:worker-a:same-id"]
    assert saved[0]["display_prose_before"] == "Inspecting the source."
    assert "display_prose_before" not in saved[1]
    assert saved[2]["display_prose_before"] == "Checking the result."
    assert saved[0]["output"] == "Observed source" and saved[0]["status"] == "completed"
    assert saved[0]["duration_ms"] == 4 and saved[0]["is_error"] is False
    assert saved[2]["output"] == "Check failed" and saved[2]["status"] == "failed"
    assert saved[3]["source_agent"] == "worker-a" and saved[3]["agent_role"] == "tester"
    assert saved[3]["arguments"] == {"file_path": "child.py"}
    assert saved[3]["output"] == "Child observed source"
    assert "display_prose_before" not in saved[3] and "Private child prose" not in str(saved)
    assert runtime.context.provider_input_tokens != 99
    runtime.memory.active_session = None
    assert runtime.memory.load_session(session_id)
    assert runtime.memory.active_session.turns[-1]["tools_used"] == saved
    runtime.memory.active_session = None
    runtime.memory.db.execute = Mock(side_effect=RuntimeError("offline database"))
    assert runtime.memory.load_session(session_id)
    assert runtime.memory.active_session.turns[-1]["tools_used"] == saved


def test_new_turn_clears_unconsumed_parent_prose_and_saved_tools(runtime):
    runtime._pending_display_prose = "Prior final response must stay in its own turn."
    runtime._current_tool_calls = [{"call_id": "old", "name": "read_file"}]

    def run(history, *_args, **_kwargs):
        emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "new", "arguments": {"file_path": "new.py"}})
        emit(runtime, EventKind.TOOL_COMPLETED, {"name": "read_file", "call_id": "new", "content": "New evidence"})
        return "New result", history

    runtime.loop.run = run
    runtime.run_agent("Inspect another file")
    saved = runtime.memory.active_session.turns[-1]["tools_used"]
    assert len(saved) == 1 and saved[0]["call_id"] == "new"
    assert "display_prose_before" not in saved[0]


def test_child_tools_do_not_consume_pending_parent_prose(runtime):
    emit(runtime, EventKind.MODEL_RESPONSE, {"display_text": "Parent observation.", "usage": {}})
    child = {"agent_id": "child", "role": "researcher", "task": "Check"}
    runtime._emit(scoped_subagent_event(RuntimeEvent(EventKind.TOOL_CALL_STARTED,
        {"name": "read_file", "call_id": "read", "arguments": {}}), child, "parent-turn"))
    emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "list_directory", "call_id": "parent", "arguments": {}})
    assert "display_prose_before" not in runtime._current_tool_calls[0]
    assert runtime._current_tool_calls[1]["display_prose_before"] == "Parent observation."


@pytest.mark.parametrize("outcome,expected", [
    ("paused", "cancelled"), ("failed", "failed"), ("completed", "unknown"),
])
def test_incomplete_tool_rows_are_terminal_without_inventing_a_result(runtime, outcome, expected):
    def run(history, *_args, **_kwargs):
        emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "done", "arguments": {}})
        emit(runtime, EventKind.TOOL_COMPLETED, {"name": "read_file", "call_id": "done", "content": "Finished evidence"})
        emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "failed", "arguments": {}})
        emit(runtime, EventKind.TOOL_FAILED, {"name": "read_file", "call_id": "failed", "content": "Missing file", "is_error": True})
        emit(runtime, EventKind.TOOL_REQUESTED, {"name": "read_file", "call_id": "pending", "arguments": {}})
        emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "running", "arguments": {}})
        if outcome == "paused":
            runtime._cancellation_flag.set()
        return ("Model request failed: lost connection" if outcome == "failed" else "Turn ended"), history

    runtime.loop.run = run
    runtime.run_agent("Inspect source")
    saved = runtime.memory.active_session.turns[-1]["tools_used"]
    assert saved[0]["status"] == "completed" and saved[0]["output"] == "Finished evidence"
    assert saved[1]["status"] == "failed" and saved[1]["output"] == "Missing file"
    assert saved[2]["status"] == saved[3]["status"] == expected
    assert "output" not in saved[2] and "output" not in saved[3]


@pytest.mark.parametrize("output", [
    "Cancelled by user before execution.",
    "CancelledByUser: Stop requested",
    "Error: Command cancelled by user.",
    "Error: CommandCancelled: Stop requested",
    "Error during parallel tool execution: InterruptedError: Command cancelled by user",
])
def test_recorded_cancellation_has_cancelled_tool_status(runtime, output):
    emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "run_terminal_command", "call_id": "cancel", "arguments": {}})
    emit(runtime, EventKind.TOOL_FAILED, {"name": "run_terminal_command", "call_id": "cancel", "content": output, "is_error": True})
    assert runtime._current_tool_calls[0]["status"] == "cancelled"
    assert runtime._current_tool_calls[0]["output"] == output


def test_successfully_read_cancellation_text_is_not_misclassified(runtime):
    emit(runtime, EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "read", "arguments": {}})
    emit(runtime, EventKind.TOOL_COMPLETED, {"name": "read_file", "call_id": "read", "content": "Cancelled by user is a documented message."})
    assert runtime._current_tool_calls[0]["status"] == "completed"
