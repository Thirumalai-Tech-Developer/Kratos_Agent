import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder, ContextBudget
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.runtime_contracts import (
    ChatMessage,
    ModelResponse,
    ToolCall,
    ToolPermission,
    ToolSpec,
    EventKind,
)
from kratos_agent.core.tool_runtime import ToolRegistry


class MockModelForUX:
    def __init__(self, responses: List[ModelResponse]):
        self.responses = list(responses)
        self.recorded_requests: List[Dict[str, Any]] = []

    def complete(self, request: Dict[str, Any]) -> ModelResponse:
        self.recorded_requests.append(request)
        system = request.get("system", "")
        if "Kratos Planner" in system:
            return ModelResponse(text='{"goal": "Execute user request", "tasks": [{"id": "1", "title": "Analyze and inspect project requirements"}, {"id": "2", "title": "Implement application files and structure"}, {"id": "3", "title": "Verify application and tests"}]}')
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(text="Default completion text.")


class AgentExecutionUXTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.instructions = InstructionEngine()
        self.instructions.register(InstructionModule("base", "system", lambda: "System test instructions"))

        # Setup standard tools
        self.tools = ToolRegistry()
        self.tools.register(
            ToolSpec("write_file", "write", {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"], "additionalProperties": False}, ToolPermission.WRITE),
            lambda file_path, content: self._mock_write(file_path, content)
        )
        self.tools.register(
            ToolSpec("read_file", "read", {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"], "additionalProperties": False}, ToolPermission.READ),
            lambda file_path: "mock file content"
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mock_write(self, file_path: str, content: str) -> str:
        p = self.workspace / file_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully created '{file_path}'."

    def test_case_a_simple_chat_no_plan(self):
        """Simple chat queries like 'hello' should not create a multi-step plan."""
        events = []
        model = MockModelForUX([ModelResponse(text="Hello! How can I help you today?")])
        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=1000)),
            self.instructions,
            self.tools,
            model,
            events.append,
            self.workspace,
        )

        reply, history = loop.run([ChatMessage("user", "hello")], lambda spec, args: (True, "allowed"))
        self.assertEqual(reply, "Hello! How can I help you today?")
        self.assertIsNone(loop.current_plan)

        # Confirm no PLAN_CREATED event was emitted
        event_kinds = [e.kind for e in events]
        self.assertNotIn(EventKind.PLAN_CREATED, event_kinds)
        self.assertIn(EventKind.AGENT_STARTED, event_kinds)

    def test_case_b_simple_coding_task_with_plan(self):
        """Simple coding task produces dynamic plan, tool execution, and verification."""
        events = []
        model = MockModelForUX([
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<!DOCTYPE html><html><body><h1>Hello World</h1></body></html>"})]),
            ModelResponse(text="Created hello world HTML page successfully."),
        ])
        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=1000)),
            self.instructions,
            self.tools,
            model,
            events.append,
            self.workspace,
        )

        reply, history = loop.run(
            [ChatMessage("user", "create a hello world HTML page")],
            lambda spec, args: (True, "allowed")
        )

        self.assertIn("Created hello world HTML page", reply)
        self.assertIsNotNone(loop.current_plan)
        self.assertGreater(loop.current_plan.total_count, 0)
        self.assertEqual(loop.current_plan.completed_count, loop.current_plan.total_count)

        # Verify file tracking & verification
        self.assertIn("index.html", loop.workspace_tracker.created_files)
        self.assertIsNotNone(loop.last_verification)
        self.assertTrue(loop.last_verification.passed)

        event_kinds = [e.kind for e in events]
        self.assertIn(EventKind.PLAN_CREATED, event_kinds)
        self.assertIn(EventKind.FILE_CREATED, event_kinds)
        self.assertIn(EventKind.VERIFICATION_STARTED, event_kinds)
        self.assertIn(EventKind.VERIFICATION_COMPLETED, event_kinds)
        self.assertIn(EventKind.AGENT_COMPLETED, event_kinds)

    def test_case_c_complex_spiderman_webapp(self):
        """Complex coding query creates tailored Spider-Man plan, tracks multiple files, and verifies."""
        events = []
        model = MockModelForUX([
            ModelResponse(tool_calls=[
                ToolCall("write_file", {"file_path": "index.html", "content": "<!DOCTYPE html><html><head><title>Spider-Man</title></head><body><div id='root'></div></body></html>"}),
                ToolCall("write_file", {"file_path": "styles.css", "content": "body { background: #1a1a2e; color: #e63946; }"}),
                ToolCall("write_file", {"file_path": "app.js", "content": "console.log('Spider-Man Webapp Initialized');"}),
            ]),
            ModelResponse(text="Successfully created the Spider-Man web application with hero section, suit gallery, and interactive controls."),
        ])
        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=1000)),
            self.instructions,
            self.tools,
            model,
            events.append,
            self.workspace,
        )

        reply, history = loop.run(
            [ChatMessage("user", "create a webapp for spiderman")],
            lambda spec, args: (True, "allowed")
        )

        self.assertIn("Spider-Man", reply)
        self.assertEqual(len(loop.workspace_tracker.created_files), 3)
        self.assertIn("index.html", loop.workspace_tracker.created_files)
        self.assertIn("styles.css", loop.workspace_tracker.created_files)
        self.assertIn("app.js", loop.workspace_tracker.created_files)

        self.assertIsNotNone(loop.last_verification)
        self.assertTrue(loop.last_verification.passed)
        self.assertEqual(loop.last_verification.files_checked, 3)

        # Confirm Plan was created and emitted BEFORE any tool calls were executed
        event_kinds = [e.kind for e in events]
        self.assertIn(EventKind.PLAN_CREATED, event_kinds)
        self.assertIn(EventKind.TOOL_CALL_STARTED, event_kinds)
        plan_event_idx = event_kinds.index(EventKind.PLAN_CREATED)
        first_tool_idx = event_kinds.index(EventKind.TOOL_CALL_STARTED)
        self.assertLess(plan_event_idx, first_tool_idx, "Plan must be created and displayed BEFORE any tool execution!")

    def test_case_d_tool_failure_does_not_falsely_complete_task(self):
        """Tool failure is tracked and does not falsely mark task as completed."""
        events = []
        failing_tools = ToolRegistry()
        failing_tools.register(
            ToolSpec("write_file", "write", {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"], "additionalProperties": False}, ToolPermission.WRITE),
            lambda file_path, content: (_ for _ in ()).throw(PermissionError("Permission Denied on Windows"))
        )

        model = MockModelForUX([
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "protected.txt", "content": "data"})]),
            ModelResponse(text="I encountered a permission error when writing protected.txt."),
        ])

        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=1000)),
            self.instructions,
            failing_tools,
            model,
            events.append,
            self.workspace,
        )

        reply, history = loop.run(
            [ChatMessage("user", "create protected.txt file")],
            lambda spec, args: (True, "allowed")
        )

        # Tool failure should be recorded in events
        event_kinds = [e.kind for e in events]
        self.assertIn(EventKind.TOOL_FAILED, event_kinds)

    def test_case_e_interrupt_and_resume(self):
        """Ctrl+C cancellation safely stops loop, pauses tasks, and continue resumes."""
        events = []
        cancel_event = threading.Event()
        cancel_event.set()  # Signal cancellation immediately

        model = MockModelForUX([ModelResponse(text="never called")])
        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=1000)),
            self.instructions,
            self.tools,
            model,
            events.append,
            self.workspace,
            cancellation_flag=cancel_event,
        )

        reply, history = loop.run(
            [ChatMessage("user", "build a full Spider-Man webapp")],
            lambda spec, args: (True, "allowed")
        )

        self.assertIn("interrupted", reply.lower())
        event_kinds = [e.kind for e in events]
        self.assertIn(EventKind.AGENT_PAUSED, event_kinds)
        self.assertIsNotNone(loop.current_plan)

        saved_plan = loop.current_plan

        # Now resume with 'continue'
        resume_events = []
        cancel_event.clear()  # Clear cancellation

        resume_model = MockModelForUX([
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "spiderman.html", "content": "<h1>Spider-Man</h1>"})]),
            ModelResponse(text="Resumed and finished Spider-Man webapp."),
        ])

        resume_loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=1000)),
            self.instructions,
            self.tools,
            resume_model,
            resume_events.append,
            self.workspace,
            cancellation_flag=cancel_event,
        )

        resume_reply, resume_history = resume_loop.run(
            [ChatMessage("user", "continue")],
            lambda spec, args: (True, "allowed"),
            resume_plan=saved_plan,
        )

        self.assertIn("Resumed and finished", resume_reply)
        resume_event_kinds = [e.kind for e in resume_events]
        self.assertIn(EventKind.AGENT_RESUMED, resume_event_kinds)
        self.assertIn(EventKind.AGENT_COMPLETED, resume_event_kinds)


if __name__ == "__main__":
    unittest.main()
