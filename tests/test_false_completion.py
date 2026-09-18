"""Tests specifically verifying prevention of false task completion, intent vs execution separation,
evidence-backed task state transitions, and truthful verification.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBuilder, ContextBudget
from kratos_agent.core.instruction_engine import InstructionEngine, InstructionModule
from kratos_agent.core.runtime_contracts import (
    ChatMessage,
    EventKind,
    ModelResponse,
    ToolCall,
    ToolPermission,
    ToolSpec,
)
from kratos_agent.core.task_manager import TaskItem, TaskState, AgentState
from kratos_agent.core.tool_runtime import ToolRegistry
from kratos_agent.core.verification_manager import VerificationManager


class MockModel:
    def __init__(self, responses: List[ModelResponse]):
        self.responses = list(responses)
        self.recorded_requests: List[Dict[str, Any]] = []

    def complete(self, request: Dict[str, Any]) -> ModelResponse:
        self.recorded_requests.append(request)
        system = request.get("system", "")
        if "Kratos Planner" in system:
            return ModelResponse(text='{"goal": "Build application", "tasks": [{"id": "1", "title": "Inspect workspace and requirements"}, {"id": "2", "title": "Scaffold index.html file"}, {"id": "3", "title": "Verify application"}]}')
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(text="Default completion text.")


class FalseCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.instructions = InstructionEngine()
        self.instructions.register(InstructionModule("base", "system", lambda: "System test instructions"))

        self.tools = ToolRegistry()
        self.tools.register(
            ToolSpec("write_file", "write", {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"], "additionalProperties": False}, ToolPermission.WRITE),
            lambda file_path, content: self._mock_write(file_path, content)
        )
        self.tools.register(
            ToolSpec("run_terminal_command", "execute", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"], "additionalProperties": False}, ToolPermission.EXECUTE),
            lambda command: "Executed command successfully."
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mock_write(self, file_path: str, content: str) -> str:
        p = self.workspace / file_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully created '{file_path}'."

    def test_model_intent_text_does_not_falsely_complete_tasks(self):
        """When model outputs only intent text (e.g. 'I will inspect the workspace'), tasks must NOT be marked COMPLETED."""
        events = []
        # Model returns natural language statements without tool calls
        model = MockModel([
            ModelResponse(text="I will inspect the workspace contents using a terminal command."),
            ModelResponse(text="I am now going to scaffold the project structure."),
            ModelResponse(text="Everything is done according to the plan."),
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
            [ChatMessage("user", "create a ben 10 webapp")],
            lambda spec, args: (True, "allowed")
        )

        # Plan must NOT be marked COMPLETED because no tools were executed
        self.assertIsNotNone(loop.current_plan)
        self.assertNotEqual(loop.current_plan.state, AgentState.COMPLETED)
        self.assertEqual(loop.current_plan.state, AgentState.FAILED)

        # Confirm AGENT_COMPLETED was NOT emitted
        event_kinds = [e.kind for e in events]
        self.assertNotIn(EventKind.AGENT_COMPLETED, event_kinds)
        self.assertIn(EventKind.AGENT_FAILED, event_kinds)

    def test_real_tool_execution_completes_task_with_evidence(self):
        """When a tool actually executes successfully, task transitions to COMPLETED with evidence."""
        events = []
        model = MockModel([
            # Step 1: Write index.html
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Ben 10</h1>"})]),
            # Step 2: Run verification command
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "npm test"})]),
            # Step 3: Final response
            ModelResponse(text="Ben 10 webapp created and verified successfully."),
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
            [ChatMessage("user", "create a ben 10 webapp")],
            lambda spec, args: (True, "allowed")
        )

        self.assertIsNotNone(loop.current_plan)
        self.assertEqual(loop.current_plan.state, AgentState.COMPLETED)
        self.assertTrue(loop.current_plan.is_all_completed)
        self.assertIn("index.html", loop.workspace_tracker.created_files)

        event_kinds = [e.kind for e in events]
        self.assertIn(EventKind.AGENT_COMPLETED, event_kinds)
        self.assertNotIn(EventKind.AGENT_FAILED, event_kinds)

    def test_tool_failure_marks_task_failed(self):
        """When tool fails, task state must be FAILED or NEEDS_ATTENTION, and overall plan must fail."""
        events = []
        failing_tools = ToolRegistry()
        failing_tools.register(
            ToolSpec("write_file", "write", {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"], "additionalProperties": False}, ToolPermission.WRITE),
            lambda file_path, content: (_ for _ in ()).throw(IOError("Disk write failed"))
        )

        model = MockModel([
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "data"})]),
            ModelResponse(text="Encountered disk error."),
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
            [ChatMessage("user", "create a ben 10 webapp")],
            lambda spec, args: (True, "allowed")
        )

        self.assertIsNotNone(loop.current_plan)
        self.assertNotEqual(loop.current_plan.state, AgentState.COMPLETED)
        self.assertEqual(loop.current_plan.state, AgentState.FAILED)

        event_kinds = [e.kind for e in events]
        self.assertIn(EventKind.TOOL_FAILED, event_kinds)
        self.assertIn(EventKind.AGENT_FAILED, event_kinds)
        self.assertNotIn(EventKind.AGENT_COMPLETED, event_kinds)

    def test_verification_fails_if_no_files_created_for_coding_task(self):
        """Verification must fail if 0 files were created for a task requiring file changes."""
        vm = VerificationManager(self.workspace)
        result = vm.verify_workspace([], verification_type="build", require_files=True)
        self.assertFalse(result.passed)
        self.assertIn("No files", result.details[0])

    def test_task_item_evidence_guard(self):
        """TaskItem accurately tracks evidence and completion."""
        task = TaskItem(id="1", title="Scaffold file")
        self.assertFalse(task.has_evidence())

        # Add concrete evidence
        task.add_evidence("write_file", {"file_path": "app.py"})
        self.assertTrue(task.has_evidence())

        task.complete("Done with tools")
        self.assertEqual(task.state, TaskState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
