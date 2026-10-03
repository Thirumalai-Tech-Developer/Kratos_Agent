"""Exercise lesson commands without importing the global provider/MCP runtime."""
import ast
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from kratos_agent.core.recovery_memory import RecoveryMemory, TEMPLATES
from kratos_agent.core.runtime_contracts import ToolCall, ToolResult
from kratos_agent.core.task_manager import AgentState, ExecutionPlan, TaskItem, TaskState
from kratos_agent.core.verification_manager import VerificationResult


@pytest.fixture
def lesson_cli(tmp_path):
    source = Path(__file__).parents[1] / "src" / "kratos_agent" / "cli.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle_lessons_command")
    output = io.StringIO()
    memory = RecoveryMemory(tmp_path)
    namespace = {
        "runtime": SimpleNamespace(loop=SimpleNamespace(recovery_memory=memory)),
        "console": Console(file=output, width=160, color_system=None),
        "Table": Table,
        "escape": escape,
    }
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["handle_lessons_command"], memory, output


def seed_lesson(memory):
    task = TaskItem("1", "Fix required command argument")
    failed = ToolCall("run_terminal_command", {})
    memory.observe(task, failed, ToolResult(failed.call_id, failed.name, "Missing required arguments: command", is_error=True))
    corrected = ToolCall("run_terminal_command", {"command": "python private-script.py --key SECRET"})
    memory.observe(task, corrected, ToolResult(corrected.call_id, corrected.name, "Exit Code: 0"))
    task.state = TaskState.COMPLETED
    plan = ExecutionPlan(goal="Fix command", tasks=[task])
    plan.state = AgentState.COMPLETED
    assert memory.commit(plan, VerificationResult(passed=True, summary="Passed project checks")) == 1


def test_empty_memory_explains_when_lessons_are_saved(lesson_cli):
    command, memory, output = lesson_cli
    command()

    assert "No verified recovery lessons yet" in output.getvalue()
    assert not memory.path.exists()


def test_cli_displays_only_verified_template_and_storage_location(lesson_cli):
    command, memory, output = lesson_cli
    seed_lesson(memory)
    command("status")
    rendered = output.getvalue()

    assert "Verified Recovery Lessons" in rendered
    assert TEMPLATES["match_schema"] in rendered
    assert "run_terminal_command / python" in rendered
    assert str(memory.path) in rendered
    assert "SECRET" not in rendered
    assert "private-script.py" not in rendered


def test_clear_removes_lessons_and_future_recall(lesson_cli):
    command, memory, output = lesson_cli
    seed_lesson(memory)
    command("clear")

    assert "Cleared 1 recovery lesson(s)" in output.getvalue()
    assert not memory.path.exists()
    assert RecoveryMemory(memory.workspace).context("Run Python") == ""


def test_unknown_command_preserves_memory(lesson_cli):
    command, memory, output = lesson_cli
    seed_lesson(memory)
    command("remove all")

    assert "Usage: /lessons [clear]" in output.getvalue()
    assert len(memory.entries()) == 1
