import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder, ContextBudget
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.prompt_builder import CORE_PROMPT_V2, SPEECH_OUTPUT_RULE
from kratos_agent.core.runtime_contracts import ChatMessage, ModelResponse, ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.task_manager import AgentState
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.output.speech_directives import DirectiveStreamFilter, extract_speech_directives


class Model:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, request):
        if "Kratos Planner" in request.get("system", ""):
            return ModelResponse(text='{"goal":"Create report","tasks":[{"id":"1","title":"Inspect workspace"},{"id":"2","title":"Create report.md"},{"id":"3","title":"Verify report"}]}')
        return self.responses.pop(0) if self.responses else ModelResponse(text="Unresolved task.")


def make_loop(tmp_path, responses, events):
    registry = ToolRegistry()
    def execute(command):
        events.append("tool")
        return "Observed output. Exit Code: 0"
    def write(file_path, content):
        (tmp_path / file_path).write_text(content, encoding="utf-8")
        return "File written"
    registry.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE), execute)
    registry.register(ToolSpec("write_file", "write", {"properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}, ToolPermission.WRITE), write)
    instructions = InstructionEngine()
    instructions.register(InstructionModule("core", "system", lambda: CORE_PROMPT_V2))
    loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=12000)), instructions, registry, Model(responses), lambda event: None, tmp_path)
    loop.on_speech = lambda text: events.append(text)
    return loop


def test_one_acknowledgement_precedes_tools_and_verified_final_is_spoken(tmp_path):
    events = []
    loop = make_loop(tmp_path, [
        ModelResponse(text="[[speak]]I'll check the workspace.[[/speak]]", tool_calls=[ToolCall("run_terminal_command", {"command": "inspect workspace"})]),
        ModelResponse(text="[[speak]]This second acknowledgement should be ignored.[[/speak]]", tool_calls=[ToolCall("write_file", {"file_path": "report.md", "content": "Verified report"})]),
        ModelResponse(text="Report saved. [[speak]]The report is ready.[[/speak]]"),
    ], events)
    reply, _ = loop.run([ChatMessage("user", "create report.md")], lambda spec, args: (True, ""))
    assert loop.current_plan.state == AgentState.COMPLETED
    assert events == ["I'll check the workspace.", "tool", "The report is ready."]
    assert "[[speak]]" not in reply


@pytest.mark.parametrize("text", ["Unmarked acknowledgement", "[[speak]]Unclosed acknowledgement"])
def test_unmarked_or_malformed_tool_acknowledgement_is_never_spoken(tmp_path, text):
    events = []
    loop = make_loop(tmp_path, [
        ModelResponse(text=text, tool_calls=[ToolCall("run_terminal_command", {"command": "inspect workspace"})]),
        ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "report.md", "content": "Report"})]),
        ModelResponse(text="Saved."),
    ], events)
    loop.run([ChatMessage("user", "create report.md")], lambda spec, args: (True, ""))
    assert events == ["tool"]


def test_failed_plan_cannot_speak_false_success(tmp_path):
    events = []
    loop = make_loop(tmp_path, [
        ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "report.md", "content": "Draft"})]),
        *[ModelResponse(text="Everything is done. [[speak]]The task is complete.[[/speak]]") for _ in range(3)],
    ], events)
    loop.tools.register(ToolSpec("write_file", "write", {"properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}}, ToolPermission.WRITE), lambda **args: (_ for _ in ()).throw(RuntimeError("Disk unavailable")))
    reply, _ = loop.run([ChatMessage("user", "create a report")], lambda spec, args: (True, ""), max_steps=10)
    assert loop.current_plan.state == AgentState.FAILED
    assert "Task incomplete" in reply
    assert events == ["The task is incomplete. Some steps still need attention."]


def test_normal_chat_receives_shared_speech_rule_without_starting_runtime():
    # Execute the real method without importing main.py's global runtime instance.
    source = Path(__file__).resolve().parents[1] / "src/kratos_agent/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KratosRuntime")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "run_chat_restricted")
    method.decorator_list = []
    module = ast.Module(body=[method], type_ignores=[])
    namespace = {"ChatMessage": ChatMessage, "SPEECH_OUTPUT_RULE": SPEECH_OUTPUT_RULE, "DirectiveStreamFilter": DirectiveStreamFilter, "extract_speech_directives": extract_speech_directives, "_recent_conversation": lambda history: history}
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    brain = Mock()
    brain.complete.return_value = ("Hello. [[speak]]Hello there.[[/speak]]", [])
    runtime = SimpleNamespace(_history=[], brain=brain, memory=Mock(), _emit=Mock(), _speak_marked_text=Mock())
    reply = namespace["run_chat_restricted"](runtime, "hello")
    assert SPEECH_OUTPUT_RULE in brain.complete.call_args.kwargs["system_instruction"]
    runtime._speak_marked_text.assert_called_once_with("Hello there.")
    assert "[[speak]]" not in reply
