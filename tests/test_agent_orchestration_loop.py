"""Tests for Agent Orchestration Loop, User Task Anchoring, Concurrency, and Anti-Hallucination."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from kratos_agent.core.agent_loop import (
    AgentLoop,
    _extract_target_dir_and_deliverables,
    _is_no_task_hallucination,
    _verify_deliverables,
)
from kratos_agent.core.context_pipeline import ContextBudget, ContextBuilder
from kratos_agent.core.runtime_contracts import (
    AgentRunState,
    ChatMessage,
    ModelResponse,
    ToolCall,
)
from kratos_agent.brain.tool_calls import extract_tool_calls_from_text


class MockInstruction:
    def build(self) -> str:
        return "Base instruction."


class MockToolRegistry:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.executed: List[str] = []

    def schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Writes text or code directly to a file on disk.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["file_path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Reads file from workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                },
            },
        ]

    def execute(self, call: ToolCall, allow_tool: Any = None):
        from kratos_agent.core.runtime_contracts import ToolResult
        self.executed.append(call.name)
        if call.name == "write_file":
            fp = str(call.arguments.get("file_path", "out.txt"))
            content = str(call.arguments.get("content", ""))
            p = Path(fp) if Path(fp).is_absolute() else (self.workspace / fp)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(call_id=call.call_id, name="write_file", content=f"Wrote {fp}")
        return ToolResult(call_id=call.call_id, name=call.name, content="Tool output")


class MockModelWithResponses:
    def __init__(self, responses: List[ModelResponse]):
        self.responses = list(responses)
        self.recorded_requests: List[Dict[str, Any]] = []

    def complete(self, request: Dict[str, Any], on_chunk: Any = None) -> ModelResponse:
        self.recorded_requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(text="Default fallback response.")


class AgentOrchestrationLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.tools = MockToolRegistry(self.workspace)
        self.instructions = MockInstruction()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_target_dir_and_deliverable_parsing(self):
        """Validates that target directory and inspect/readme.md deliverable are cleanly extracted from query."""
        query = '"C:\\Users\\thiru\\Documents\\AI Job Apply" inspect the web page and give detailed report. stored in same inspect folder named as readme.md'
        target_dir, deliverables = _extract_target_dir_and_deliverables(query, self.workspace)
        self.assertIsNotNone(target_dir)
        self.assertTrue("AI Job Apply" in target_dir)
        self.assertIn("inspect/readme.md", deliverables)

    def test_compaction_never_prunes_root_user_request(self):
        """Validates that history compaction pins messages[0] so the user query is never lost."""
        builder = ContextBuilder(ContextBudget(max_input_tokens=200))
        root_query = '"C:\\Users\\thiru\\Documents\\AI Job Apply" inspect the web page and give detailed report.'
        history = [ChatMessage("user", root_query)]
        # Add 40 massive tool results that exceed budget
        call_json = '{"file_path":"test.py"}'
        for i in range(40):
            history.append(ChatMessage("assistant", f"call:read_file{call_json}", metadata={"tool_calls": [{"id": f"c{i}", "name": "read_file", "arguments": {}}]}))
            history.append(ChatMessage("tool", f"Result content for step {i} " * 20, tool_call_id=f"c{i}", name="read_file"))

        assembled = builder.assemble(
            instruction_sections="You are Kratos.",
            history=history,
            tools=[],
            workspace={"cwd": str(self.workspace)},
            run_state=AgentRunState(run_id="run_test", user_request=root_query, workspace=self.workspace),
        )

        compacted_messages = assembled["request"]["messages"]
        # Root message must be preserved
        user_messages = [m for m in compacted_messages if m["role"] == "user"]
        self.assertTrue(any(root_query in m["content"] for m in user_messages))

    def test_anti_hallucination_nudges_model_when_no_task_claimed(self):
        """Validates that if model claims 'no task in your message' mid-run, runtime intercepts and continues."""
        hallucination_response = (
            "I'm ready to work, but there's no task in your last message — "
            "it's the Kratos operating instructions plus my loaded memory. So there's nothing to execute yet."
        )
        responses = [
            # Turn 1: Model inspects file
            ModelResponse(
                text="Inspecting test.py",
                tool_calls=[ToolCall("read_file", {"file_path": "test.py"})],
            ),
            # Turn 2: Model hallucinates "there's no task"
            ModelResponse(text=hallucination_response),
            # Turn 3: Model receives runtime correction nudge and writes deliverable
            ModelResponse(
                text="Proceeding with report generation.",
                tool_calls=[ToolCall("write_file", {"file_path": "inspect/readme.md", "content": "# Inspection Report\nVerified."})],
            ),
            # Turn 4: Final completion
            ModelResponse(text="✓ Inspection completed and report written."),
        ]

        model = MockModelWithResponses(responses)
        events = []
        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=10000)),
            self.instructions,
            self.tools,
            model,
            events.append,
            self.workspace,
        )

        query = '"C:\\Users\\thiru\\Documents\\AI Job Apply" inspect the web page and give detailed report. stored in same inspect folder named as readme.md'
        reply, final_history = loop.run([ChatMessage("user", query)], allow_tool=lambda spec, args: (True, "allowed"))

        # The deliverable must have been written to disk
        report_file = self.workspace / "inspect" / "readme.md"
        self.assertTrue(report_file.exists())
        self.assertIn("Verified", report_file.read_text(encoding="utf-8"))

        # Confirm runtime state completed
        self.assertIsNotNone(loop.current_run)
        self.assertEqual(loop.current_run.status, "completed")
        self.assertIn("inspect/readme.md", loop.current_run.written_files)

    def test_deliverable_verification_blocks_premature_completion(self):
        """Validates that if model outputs conversational text before deliverable exists, it is nudged to write it."""
        responses = [
            # Turn 1: Model says it did analysis, but didn't call write_file
            ModelResponse(text="I have inspected the project and everything looks good!"),
            # Turn 2: Nudged by runtime, model writes the file
            ModelResponse(
                text="Writing inspect/readme.md now.",
                tool_calls=[ToolCall("write_file", {"file_path": "inspect/readme.md", "content": "# Detailed Report\nCompleted."})],
            ),
            # Turn 3: Final confirmation
            ModelResponse(text="Report has been generated successfully."),
        ]

        model = MockModelWithResponses(responses)
        events = []
        loop = AgentLoop(
            ContextBuilder(ContextBudget(max_input_tokens=10000)),
            self.instructions,
            self.tools,
            model,
            events.append,
            self.workspace,
        )

        query = "inspect project and write report stored in same inspect folder named as readme.md"
        reply, final_history = loop.run([ChatMessage("user", query)], allow_tool=lambda spec, args: (True, "allowed"))

        report_file = self.workspace / "inspect" / "readme.md"
        self.assertTrue(report_file.exists())
        self.assertEqual(loop.current_run.status, "completed")

    def test_windows_path_with_backslashes_in_json_tool_calls(self):
        """Validates that Windows paths with backslashes parse cleanly in tool calls without JSONDecodeError."""
        raw_text = (
            'call:write_file{"file_path": "C:\\Users\\thiru\\Documents\\AI Job Apply\\inspect\\readme.md", '
            '"content": "# Report"}'
        )
        _, parsed_calls = extract_tool_calls_from_text(raw_text)
        self.assertEqual(len(parsed_calls), 1)
        self.assertEqual(parsed_calls[0]["name"], "write_file")
        fp = parsed_calls[0]["args"]["file_path"]
        self.assertTrue("AI Job Apply" in fp)
        self.assertTrue("inspect" in fp)


if __name__ == "__main__":
    unittest.main()
