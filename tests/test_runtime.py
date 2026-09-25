import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder, ContextBudget
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.runtime_contracts import ChatMessage, ModelResponse, ToolCall, ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.live.runtime import _resolve_live_chat_reply


class ScriptedModel:
    def __init__(self):
        self.responses = [ModelResponse(tool_calls=[ToolCall("add", {"left": "2", "right": "3"})]), ModelResponse(text="The result is 5.")]
    def complete(self, request):
        return self.responses.pop(0)


class RuntimeLoopTests(unittest.TestCase):
    def test_live_generic_error_uses_correlated_verified_task_result(self):
        status = {
            "last_result": {
                "task_id": "TASK-new",
                "status": "success",
                "verified": True,
                "evidence": {"message": "calculator and tests are in place"},
            }
        }
        reply = _resolve_live_chat_reply("Sorry, a system error occurred.", "TASK-old", status)
        self.assertIn("completed and verified", reply)
        self.assertIn("calculator and tests are in place", reply)

    def test_live_generic_error_uses_correlated_task_diagnostic(self):
        status = {
            "last_result": {
                "task_id": "TASK-new",
                "status": "failed",
                "error": {
                    "component": "brain",
                    "stage": "model_request",
                    "user_message": "Provider returned HTTP 429",
                    "recovery_action": "Retry later",
                },
            }
        }
        reply = _resolve_live_chat_reply("I'm sorry, but a system error occurred.", "TASK-old", status)
        self.assertIn("brain during model_request", reply)
        self.assertIn("HTTP 429", reply)
        self.assertIn("Retry later", reply)

    def test_live_generic_error_without_new_task_signals_agent_fallback(self):
        status = {"last_result": {"task_id": "TASK-old", "status": "success", "verified": True}}
        self.assertEqual(
            _resolve_live_chat_reply("I couldn't process your request.", "TASK-old", status),
            "",
        )

    def test_live_normal_reply_is_preserved(self):
        self.assertEqual(
            _resolve_live_chat_reply("I created and tested the calculator.", None, {}),
            "I created and tested the calculator.",
        )

    def test_nonzero_terminal_exit_is_a_tool_error(self):
        tools = ToolRegistry()
        tools.register(
            ToolSpec("run_terminal_command", "run command", {}, ToolPermission.EXECUTE),
            lambda: "ParserError: bad quote\nExit Code: 1",
        )
        result = tools.execute(
            ToolCall("run_terminal_command", {}),
            lambda spec, args: (True, "allowed"),
        )
        self.assertTrue(result.is_error)

    def test_structured_terminal_rejection_is_a_tool_error(self):
        tools = ToolRegistry()
        tools.register(
            ToolSpec("run_terminal_command", "run command", {}, ToolPermission.EXECUTE),
            lambda: '{"ok": false, "code": "SOURCE_AS_COMMAND"}',
        )
        result = tools.execute(
            ToolCall("run_terminal_command", {}),
            lambda spec, args: (True, "allowed"),
        )
        self.assertTrue(result.is_error)

    def test_tool_result_is_fed_back_before_final_response(self):
        instructions = InstructionEngine()
        instructions.register(InstructionModule("base", "system", lambda: "test"))
        tools = ToolRegistry()
        tools.register(ToolSpec("add", "add numbers", {"type": "object", "properties": {"left": {"type": "string"}, "right": {"type": "string"}}, "required": ["left", "right"], "additionalProperties": False}, ToolPermission.READ), lambda left, right: str(int(left) + int(right)))
        events = []
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=1000)), instructions, tools, ScriptedModel(), events.append, Path.cwd())
        result, history = loop.run([ChatMessage("user", "add two and three")], lambda spec, args: (True, "test"))
        self.assertEqual(result, "The result is 5.")
        self.assertTrue(any(message.role == "tool" and message.content == "5" for message in history))

    def test_invalid_arguments_stay_in_history_as_a_tool_error(self):
        instructions = InstructionEngine()
        instructions.register(InstructionModule("base", "system", lambda: "test"))
        tools = ToolRegistry()
        tools.register(ToolSpec("read", "read", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}, ToolPermission.READ), lambda path: path)
        model = type("M", (), {"complete": lambda self, request: ModelResponse(text="done") if any(m["role"] == "tool" for m in request["messages"]) else ModelResponse(tool_calls=[ToolCall("read", {"wrong": "x"})])})()
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=1000)), instructions, tools, model, lambda event: None, Path.cwd())
        _, history = loop.run([ChatMessage("user", "read")], lambda spec, args: (True, "test"))
        self.assertTrue(history[-2].metadata["is_error"])


if __name__ == "__main__":
    unittest.main()
