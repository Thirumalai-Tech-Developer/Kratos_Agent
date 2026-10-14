from pathlib import Path
import ast
from types import MethodType, SimpleNamespace
import re
import threading
from unittest.mock import Mock

from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

ROOT = Path(__file__).resolve().parents[1]


def _load_status_helper():
    path = ROOT / "src/kratos_agent/main.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_derive_turn_status"
    )
    namespace = {
        "Any": object,
        "List": list,
        "Dict": dict,
        "_ACTIONABLE_REQUEST_PATTERN": re.compile(
            r"\b(?:make|create|build|implement|generate|scaffold|develop|write)\b.*\b(?:website|webapp|web|site|app|project|file|page|code)\b",
            re.IGNORECASE,
        ),
    }
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace["_derive_turn_status"]


def _plan(state, task_states):
    return SimpleNamespace(
        state=SimpleNamespace(value=state),
        tasks=[SimpleNamespace(state=SimpleNamespace(value=s)) for s in task_states],
    )


def test_zero_tool_mutation_request_is_never_persisted_as_completed():
    derive = _load_status_helper()
    assert derive(
        "Done — I created your site.",
        cancelled=False,
        plan=_plan("failed", ["failed"]),
        tool_calls=[],
        user_request="can you make the spiderman website in documents",
        verification_passed=False,
    ) == "failed"


def test_completed_plan_requires_real_tool_calls_and_verification():
    derive = _load_status_helper()
    plan = _plan("completed", ["completed"])
    assert derive(
        "Done — verified.",
        cancelled=False,
        plan=plan,
        tool_calls=[{"name": "write_file", "call_id": "1"}],
        user_request="create a website",
        verification_passed=True,
    ) == "completed"

    assert derive(
        "Done — verified.",
        cancelled=False,
        plan=plan,
        tool_calls=[],
        user_request="create a website",
        verification_passed=True,
    ) == "failed"


def test_normal_chat_without_plan_can_complete_without_tools():
    derive = _load_status_helper()
    assert derive(
        "Hello.",
        cancelled=False,
        plan=None,
        tool_calls=[],
        user_request="hello",
        verification_passed=None,
    ) == "completed"


def test_agent_step_limit_is_persisted_as_failure():
    derive = _load_status_helper()
    assert derive(
        "Stopped after 32 agent steps to prevent an unbounded tool loop.",
        cancelled=False,
        plan=None,
        tool_calls=[{"name": "run_terminal_command", "call_id": "1"}],
        user_request="solve the task",
        verification_passed=None,
    ) == "failed"


def test_tool_requested_and_started_count_one_actual_call():
    path = ROOT / "src/kratos_agent/main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KratosRuntime")
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)
               and node.name in {"_emit", "_record_saved_tool_event"}]
    namespace = {"Any": object, "RuntimeEvent": RuntimeEvent, "threading": threading, "re": re}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    runtime = SimpleNamespace(_current_tool_calls=[], _event_store=Mock(), context=Mock())
    runtime._record_saved_tool_event = MethodType(namespace["_record_saved_tool_event"], runtime)
    emit = MethodType(namespace["_emit"], runtime)
    payload = {"call_id": "read-one", "name": "read_file", "arguments": {"file_path": "README.md"}}
    emit(RuntimeEvent(EventKind.TOOL_REQUESTED, payload))
    emit(RuntimeEvent(EventKind.TOOL_CALL_STARTED, payload))
    assert len(runtime._current_tool_calls) == 1
    assert runtime._current_tool_calls[0]["name"] == "read_file"
    assert runtime._current_tool_calls[0]["status"] == "running"


def test_continue_keeps_unfinished_work_and_ignores_completed_historical_plans():
    path = ROOT / "src/kratos_agent/main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_resumable_plan")
    namespace = {"Any": object}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    resumable = namespace["_resumable_plan"]
    completed = SimpleNamespace(get_unfinished_tasks=lambda: [])
    failed = SimpleNamespace(get_unfinished_tasks=lambda: [SimpleNamespace(state="failed")])
    assert resumable(None) is None
    assert resumable(SimpleNamespace(get_plan=lambda: None)) is None
    assert resumable(SimpleNamespace(get_plan=lambda: completed)) is None
    assert resumable(SimpleNamespace(get_plan=lambda: failed)) is failed
