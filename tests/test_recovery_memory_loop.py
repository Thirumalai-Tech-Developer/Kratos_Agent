"""Integration contracts for evidence-gated recovery memory in the agent loop."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.recovery_memory import RecoveryMemory
from kratos_agent.core.context_pipeline import ContextBudget, ContextBuilder
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.runtime_contracts import (
    ChatMessage,
    EventKind,
    ModelResponse,
    ToolCall,
    ToolPermission,
    ToolSpec,
)
from kratos_agent.core.task_manager import AgentState, TaskState
from kratos_agent.core.tool_runtime import ToolRegistry


class SequenceModel:
    """Produce a real plan, then deterministic tool results without a provider."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, request, on_chunk=None):
        self.requests.append(request)
        if "Kratos Planner" in request.get("system", ""):
            return ModelResponse(text=json.dumps({
                "goal": "Fix Python command syntax and create a research report",
                "tasks": [
                    {"id": "1", "title": "Inspect Python command syntax"},
                    {"id": "2", "title": "Create the report"},
                    {"id": "3", "title": "Verify the report"},
                ],
            }))
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(text="The report is complete.")


def make_loop(workspace: Path, responses, *, execute=None, read=None):
    workspace.mkdir(parents=True, exist_ok=True)
    tools = ToolRegistry()

    def write_file(file_path, content):
        path = workspace / file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Successfully created '{file_path}'."

    tools.register(
        ToolSpec("write_file", "Write a report", {
            "type": "object",
            "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["file_path", "content"],
            "additionalProperties": False,
        }, ToolPermission.WRITE),
        write_file,
    )
    tools.register(
        ToolSpec("run_terminal_command", "Execute a Python command", {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        }, ToolPermission.EXECUTE),
        execute or (lambda command: "OUTPUT: recovered\nExit Code: 0"),
    )
    tools.register(
        ToolSpec("read_file", "Inspect a Python input", {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
            "additionalProperties": False,
        }, ToolPermission.READ),
        read or (lambda file_path: "Python input inspected."),
    )
    instructions = InstructionEngine()
    instructions.register(InstructionModule("base", "system", lambda: "Follow the requested task."))
    model = SequenceModel(responses)
    events = []
    loop = AgentLoop(
        ContextBuilder(ContextBudget(max_input_tokens=12000)),
        instructions,
        tools,
        model,
        events.append,
        workspace,
    )
    return loop, model, events


def run_report(loop, *, name="report.md"):
    return loop.run(
        [ChatMessage("user", f"Fix Python command syntax and create {name} with the result")],
        lambda spec, args: (True, "allowed"),
        max_steps=12,
    )


def report_call(name="report.md", content="# Research\nRecovered Python command output."):
    return ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": name, "content": content})])


@pytest.mark.parametrize("failure", ["missing_arguments", "parser_error"])
def test_corrected_execution_is_persisted_and_injected_after_verified_completion(tmp_path, failure):
    def execute(command):
        if command == "python broken quoting":
            raise RuntimeError("ParserError: Python command syntax has an unexpected token")
        return "OUTPUT: recovered\nExit Code: 0"

    failed_args = {} if failure == "missing_arguments" else {"command": "python broken quoting"}
    loop, _, events = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", failed_args)]),
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "python -c print(42)"})]),
        report_call(),
        ModelResponse(text="The report is complete and verified."),
    ], execute=execute)
    run_report(loop)

    assert loop.current_plan.state == AgentState.COMPLETED
    assert loop.last_verification.passed
    assert EventKind.TOOL_FAILED in [event.kind for event in events]
    assert len(loop.recovery_memory.entries()) == 1
    store = tmp_path / ".kratos" / "recovery_memory.json"
    persisted = json.loads(store.read_text(encoding="utf-8"))
    assert persisted["version"] == 1
    assert len(persisted["lessons"]) == 1

    # Start a different AgentLoop: neither its run state nor its task evidence
    # contains the first run. Retrieval must come from the workspace store.
    restored, model, _ = make_loop(tmp_path, [ModelResponse(text="Use the required command field and correct Python syntax.")])
    query = "Explain Python command syntax and recovery errors"
    lesson_context = restored.recovery_memory.context(query)
    assert lesson_context, "A relevant persisted lesson should be retrievable."
    restored.run([ChatMessage("user", query)], lambda spec, args: (True, "allowed"), max_steps=3)
    execution_requests = [request for request in model.requests if "Kratos Planner" not in request.get("system", "")]
    assert execution_requests
    assert lesson_context in execution_requests[-1]["system"]

    isolated, _, _ = make_loop(tmp_path / "another-workspace", [ModelResponse(text="Hello.")])
    assert isolated.recovery_memory.entries() == []
    assert not isolated.recovery_memory.context(query)


def test_unrelated_report_write_cannot_save_an_unrecovered_failure(tmp_path):
    loop, _, events = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {})]),
        report_call(content="# Draft\nThe command never ran successfully."),
        ModelResponse(text="Everything is complete and verified."),
    ])
    reply, _ = run_report(loop)

    assert (tmp_path / "report.md").is_file()
    assert loop.current_plan.state == AgentState.FAILED
    assert any(task.state == TaskState.FAILED for task in loop.current_plan.tasks)
    assert "Task incomplete" in reply
    assert EventKind.AGENT_COMPLETED not in [event.kind for event in events]
    assert loop.recovery_memory.entries() == []


def test_successful_correction_is_not_saved_when_final_verification_fails(tmp_path):
    loop, _, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {})]),
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "python -c print(42)"})]),
        report_call(name="report.py", content="def malformed(:\n    pass\n"),
        ModelResponse(text="Everything is complete and verified."),
    ])
    run_report(loop, name="report.py")

    assert loop.current_plan.state == AgentState.FAILED
    assert not loop.last_verification.passed
    assert loop.recovery_memory.entries() == []


def test_read_calls_in_one_wave_keep_their_original_task_binding(tmp_path, monkeypatch):
    loop, _, events = make_loop(tmp_path, [
        ModelResponse(tool_calls=[
            ToolCall("read_file", {"file_path": "first.py"}),
            ToolCall("read_file", {"file_path": "second.py"}),
        ]),
        report_call(),
        ModelResponse(text="The report is complete."),
    ])
    bindings = []
    observe = RecoveryMemory.observe

    def record_binding(memory, task, call, result):
        bindings.append((call.name, call.arguments.get("file_path"), task.id if task else None))
        return observe(memory, task, call, result)

    monkeypatch.setattr(RecoveryMemory, "observe", record_binding)
    run_report(loop)

    reads = [binding for binding in bindings if binding[0] == "read_file"]
    assert reads == [("read_file", "first.py", "1"), ("read_file", "second.py", "1")]
    assert loop.current_plan.state == AgentState.COMPLETED
    assert loop.recovery_memory.entries() == []
    started = [event.payload["id"] for event in events if event.kind == EventKind.TASK_STARTED]
    assert started == ["1", "2", "3"]


def test_successful_read_in_same_wave_cannot_recover_an_earlier_failed_read(tmp_path):
    def read(file_path):
        if file_path == "missing.py":
            raise FileNotFoundError("No such file: missing.py")
        return "Python input inspected."

    loop, _, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[
            ToolCall("read_file", {"file_path": "missing.py"}),
            ToolCall("read_file", {"file_path": "present.py"}),
        ]),
        report_call(),
        ModelResponse(text="The report is complete."),
    ], read=read)
    reply, _ = run_report(loop)

    assert loop.current_plan.state == AgentState.FAILED
    assert loop.current_plan.tasks[0].state == TaskState.FAILED
    assert loop.current_plan.tasks[0].retry_required_tool == "read_file"
    assert "Task incomplete" in reply
    assert loop.recovery_memory.entries() == []


def test_recalled_lesson_does_not_complete_a_new_failed_task(tmp_path):
    successful, _, _ = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {})]),
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "python -c print(42)"})]),
        report_call(),
        ModelResponse(text="The report is complete."),
    ])
    run_report(successful)
    assert len(successful.recovery_memory.entries()) == 1

    failed, _, events = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall("run_terminal_command", {})]),
        report_call(name="second-report.md", content="# Draft\nNew execution is still unresolved."),
        ModelResponse(text="The remembered recovery proves everything is complete."),
    ])
    run_report(failed, name="second-report.md")

    assert failed.current_plan.state == AgentState.FAILED
    assert failed.current_plan.tasks[0].state == TaskState.FAILED
    assert failed.current_plan.tasks[0].retry_required_tool == "run_terminal_command"
    assert EventKind.AGENT_COMPLETED not in [event.kind for event in events]
    assert len(failed.recovery_memory.entries()) == 1
