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

    def test_created_report_does_not_resurrect_failed_task(self):
        events = []
        self.tools.register(
            ToolSpec("run_terminal_command", "execute", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE),
            lambda command: (_ for _ in ()).throw(RuntimeError("Research failed")),
        )
        model = MockModel([
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "research"})]),
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Draft</h1>"})]),
            ModelResponse(text="Status: completed. All files written and verified."),
        ])
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=1000)), self.instructions, self.tools, model, events.append, self.workspace)
        reply, _ = loop.run([ChatMessage("user", "create a webapp")], lambda spec, args: (True, "allowed"))
        self.assertTrue((self.workspace / "index.html").exists())
        self.assertEqual(loop.current_plan.state, AgentState.FAILED)
        self.assertTrue(any(task.state == TaskState.FAILED for task in loop.current_plan.tasks))
        self.assertNotIn(EventKind.AGENT_COMPLETED, [event.kind for event in events])
        self.assertNotIn("Status: completed", reply)

    def test_corrected_retry_recovers_original_task(self):
        seen = []
        def execute(command):
            seen.append(command)
            if command == "broken research":
                raise RuntimeError("Invalid command; use corrected research")
            return "Actual research output"
        self.tools.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE), execute)
        model = MockModel([
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "broken research"})]),
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "corrected research"})]),
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Results</h1>"})]),
            ModelResponse(text="Completed with research output"),
        ])
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=4000)), self.instructions, self.tools, model, lambda event: None, self.workspace)
        loop.run([ChatMessage("user", "create a webapp")], lambda spec, args: (True, ""))
        self.assertEqual(seen, ["broken research", "corrected research"])
        self.assertEqual(loop.current_plan.tasks[0].retry_count, 1)
        self.assertEqual(loop.current_plan.tasks[0].state, TaskState.COMPLETED)
        self.assertEqual(loop.current_plan.state, AgentState.COMPLETED)

    def test_retries_are_bounded_and_failure_survives_saved_plan(self):
        self.tools.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE), lambda command: (_ for _ in ()).throw(RuntimeError("Unavailable source")))
        model = MockModel([
            *[ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": command})]) for command in ("first attempt", "corrected attempt", "alternate attempt")],
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Draft</h1>"})]),
            ModelResponse(text="Completed"),
        ])
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=4000)), self.instructions, self.tools, model, lambda event: None, self.workspace)
        loop.run([ChatMessage("user", "create a webapp")], lambda spec, args: (True, ""))
        task = loop.current_plan.tasks[0]
        self.assertEqual(task.retry_count, 2)
        self.assertEqual(task.state, TaskState.FAILED)
        restored = TaskItem.from_dict(task.to_dict())
        self.assertEqual(restored.retry_required_tool, "run_terminal_command")
        self.assertEqual(restored.state, TaskState.FAILED)

    def test_research_can_recover_using_another_tool(self):
        self.tools.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}}, ToolPermission.EXECUTE), lambda command: (_ for _ in ()).throw(RuntimeError("Shell unavailable")))
        self.tools.register(ToolSpec("fetch_url", "read source", {"properties": {"url": {"type": "string"}}}, ToolPermission.NETWORK), lambda url: "Source-backed research result")
        model = MockModel([
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "research"})]),
            ModelResponse(tool_calls=[ToolCall("fetch_url", {"url": "https://example.com/source"})]),
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Source result</h1>"})]),
            ModelResponse(text="Completed after fallback"),
        ])
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=4000)), self.instructions, self.tools, model, lambda event: None, self.workspace)
        loop.run([ChatMessage("user", "create a webapp")], lambda spec, args: (True, ""))
        self.assertEqual(loop.current_plan.state, AgentState.COMPLETED)
        self.assertIsNone(loop.current_plan.tasks[0].retry_required_tool)

    def test_continue_retries_failed_plan_and_emits_completion_after_recovery(self):
        def execute(command):
            if command == "broken":
                raise RuntimeError("Incorrect arguments")
            return "Verified research result"
        self.tools.register(ToolSpec("run_terminal_command", "execute", {"properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE), execute)
        model = MockModel([
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "broken"})]),
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Draft</h1>"})]),
            ModelResponse(text="Completed"),
        ])
        events = []
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=4000)), self.instructions, self.tools, model, events.append, self.workspace)
        _, history = loop.run([ChatMessage("user", "create a webapp")], lambda spec, args: (True, ""))
        self.assertEqual(loop.current_plan.state, AgentState.FAILED)
        saved_plan = loop.current_plan
        model.responses = [
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"command": "corrected research"})]),
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Verified result</h1>"})]),
            ModelResponse(text="Completed after correction"),
        ]
        events.clear()
        history.append(ChatMessage("user", "continue"))
        loop.run(history, lambda spec, args: (True, ""), resume_plan=saved_plan)
        self.assertEqual(loop.current_plan.state, AgentState.COMPLETED)
        self.assertIsNone(loop.current_plan.tasks[0].retry_required_tool)
        self.assertIn(EventKind.AGENT_COMPLETED, [event.kind for event in events])

    def test_temporary_probe_runs_extracts_and_cleans_without_becoming_deliverable(self):
        from unittest.mock import patch
        import sys
        from kratos_agent.utils.tools import run_terminal_command
        self.tools.register(ToolSpec("run_terminal_command", "execute", {"properties": {"argv": {"type": "array"}, "working_directory": {"type": "string"}}}, ToolPermission.EXECUTE), run_terminal_command)
        captured = []
        def read(file_path):
            captured.append(Path(file_path))
            return Path(file_path).read_text(encoding="utf-8")
        self.tools.register(ToolSpec("read_file", "read", {"properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}, ToolPermission.READ), read)
        model = MockModel([
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "scratch/probe.py", "content": "from pathlib import Path\nPath('scratch/raw.json').write_text('{\"price\": 429}', encoding='utf-8')\nprint('probe finished')"})]),
            ModelResponse(tool_calls=[ToolCall("run_terminal_command", {"argv": [sys.executable, "scratch/probe.py"]})]),
            ModelResponse(tool_calls=[ToolCall("read_file", {"file_path": "scratch/raw.json"})]),
            ModelResponse(tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Extracted price: 429</h1>"})]),
            ModelResponse(text="Completed"),
        ])
        loop = AgentLoop(ContextBuilder(ContextBudget(max_input_tokens=4000)), self.instructions, self.tools, model, lambda event: None, self.workspace)
        with patch("kratos_agent.utils.tools.approval_gate.check_shell", return_value=True):
            loop.run([ChatMessage("user", "create a webapp")], lambda spec, args: (True, ""))
        self.assertEqual(loop.current_plan.state, AgentState.COMPLETED)
        self.assertEqual(loop.workspace_tracker.created_files, {"index.html"})
        self.assertFalse((self.workspace / "scratch").exists())
        self.assertEqual(len(captured), 1)
        self.assertFalse(captured[0].parent.parent.exists())
        self.assertEqual(len(loop.current_plan.tasks[0].evidence), 2)  # helper write + actual execution

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
