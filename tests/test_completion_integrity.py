from pathlib import Path
import ast
from types import SimpleNamespace
import re

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


def test_tool_started_events_are_counted_in_runtime_source():
    source = (ROOT / "src/kratos_agent/main.py").read_text(encoding="utf-8")
    assert 'event.kind.value in {"tool.requested", "tool.started"}' in source
