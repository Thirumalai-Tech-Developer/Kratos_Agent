"""Unit tests for parallel tool execution, wave partitioning, and multi-subagent concurrency."""
import json
import os
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kratos_agent.brain.config import get_max_parallel_workers, is_parallel_execution_enabled
from kratos_agent.core.agent_loop import (
    AgentLoop,
    format_tool_action_label,
    partition_tool_waves,
)
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.runtime_contracts import (
    ChatMessage,
    EventKind,
    ModelResponse,
    ToolCall,
    ToolResult,
)
from kratos_agent.core.subagents import SubagentManager, SubagentResult
from kratos_agent.utils.tools import (
    set_parallel_subagent_runner,
    spawn_parallel_subagents,
)


class ParallelConfigTests(unittest.TestCase):
    def test_default_config(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(is_parallel_execution_enabled())
            self.assertEqual(get_max_parallel_workers(), 8)

    def test_disabled_config(self):
        with patch.dict(os.environ, {"KRATOS_PARALLEL_EXECUTION": "false"}, clear=True):
            self.assertFalse(is_parallel_execution_enabled())
        with patch.dict(os.environ, {"KRATOS_PARALLEL_EXECUTION": "0"}, clear=True):
            self.assertFalse(is_parallel_execution_enabled())

    def test_custom_max_workers(self):
        with patch.dict(os.environ, {"KRATOS_MAX_PARALLEL_WORKERS": "16"}, clear=True):
            self.assertEqual(get_max_parallel_workers(), 16)
        # Clamped to minimum 1 if <= 0
        with patch.dict(os.environ, {"KRATOS_MAX_PARALLEL_WORKERS": "-5"}, clear=True):
            self.assertEqual(get_max_parallel_workers(), 1)
        # Fallback to 8 if invalid string
        with patch.dict(os.environ, {"KRATOS_MAX_PARALLEL_WORKERS": "invalid"}, clear=True):
            self.assertEqual(get_max_parallel_workers(), 8)


class WavePartitioningTests(unittest.TestCase):
    def test_pure_read_tools_single_wave(self):
        calls = [
            ToolCall(name="read_file", arguments={"file_path": "a.py"}, call_id="1"),
            ToolCall(name="read_file", arguments={"file_path": "b.py"}, call_id="2"),
            ToolCall(name="grep_search", arguments={"query": "def foo"}, call_id="3"),
            ToolCall(name="list_directory", arguments={"directory_path": "src"}, call_id="4"),
        ]
        waves = partition_tool_waves(calls)
        self.assertEqual(len(waves), 1)
        self.assertEqual(len(waves[0]), 4)

    def test_distinct_file_writes_single_wave(self):
        calls = [
            ToolCall(name="write_file", arguments={"file_path": "foo.txt", "content": "1"}, call_id="1"),
            ToolCall(name="write_file", arguments={"file_path": "bar.txt", "content": "2"}, call_id="2"),
        ]
        waves = partition_tool_waves(calls)
        self.assertEqual(len(waves), 1)
        self.assertEqual(len(waves[0]), 2)

    def test_same_file_write_conflict_splits_waves(self):
        calls = [
            ToolCall(name="write_file", arguments={"file_path": "foo.txt", "content": "1"}, call_id="1"),
            ToolCall(name="edit_file", arguments={"file_path": "foo.txt", "target": "1", "replacement": "2"}, call_id="2"),
        ]
        waves = partition_tool_waves(calls)
        self.assertEqual(len(waves), 2)
        self.assertEqual([c.call_id for c in waves[0]], ["1"])
        self.assertEqual([c.call_id for c in waves[1]], ["2"])

    def test_read_after_write_dependency_splits_waves(self):
        calls = [
            ToolCall(name="write_file", arguments={"file_path": "config.json", "content": "{}"}, call_id="w1"),
            ToolCall(name="read_file", arguments={"file_path": "config.json"}, call_id="r1"),
        ]
        waves = partition_tool_waves(calls)
        self.assertEqual(len(waves), 2)
        self.assertEqual(waves[0][0].call_id, "w1")
        self.assertEqual(waves[1][0].call_id, "r1")

    def test_barrier_tool_isolation(self):
        calls = [
            ToolCall(name="read_file", arguments={"file_path": "a.txt"}, call_id="r1"),
            ToolCall(name="run_terminal_command", arguments={"command": "npm test"}, call_id="b1"),
            ToolCall(name="read_file", arguments={"file_path": "b.txt"}, call_id="r2"),
            ToolCall(name="read_file", arguments={"file_path": "c.txt"}, call_id="r3"),
        ]
        waves = partition_tool_waves(calls)
        self.assertEqual(len(waves), 3)
        self.assertEqual([c.call_id for c in waves[0]], ["r1"])
        self.assertEqual([c.call_id for c in waves[1]], ["b1"])
        self.assertEqual([c.call_id for c in waves[2]], ["r2", "r3"])

    def test_spawn_parallel_subagents_barrier(self):
        calls = [
            ToolCall(name="read_file", arguments={"file_path": "a.txt"}, call_id="r1"),
            ToolCall(name="spawn_parallel_subagents", arguments={"subagents": []}, call_id="sp1"),
        ]
        waves = partition_tool_waves(calls)
        self.assertEqual(len(waves), 2)
        self.assertEqual(waves[0][0].call_id, "r1")
        self.assertEqual(waves[1][0].call_id, "sp1")


class ParallelToolExecutionTimingTests(unittest.TestCase):
    def test_concurrent_execution_speedup(self):
        """All mock read tools execute simultaneously on concurrent threads."""
        calls = [
            ToolCall(name="read_file", arguments={"file_path": "file1.txt"}, call_id="c1"),
            ToolCall(name="read_file", arguments={"file_path": "file2.txt"}, call_id="c2"),
            ToolCall(name="read_file", arguments={"file_path": "file3.txt"}, call_id="c3"),
        ]

        step1_response = ModelResponse(text="", tool_calls=calls, finish_reason="tool_calls")
        step2_response = ModelResponse(text="Read all 3 files successfully.", tool_calls=[], finish_reason="stop")

        mock_model = MagicMock()
        mock_model.complete.side_effect = [step1_response, step2_response]

        mock_tools = MagicMock()
        mock_tools.schemas.return_value = [{"name": "read_file"}]

        max_concurrent_active = 0
        current_active = 0
        lock = threading.Lock()

        def mock_execute(call, allow_tool=None):
            nonlocal max_concurrent_active, current_active
            with lock:
                current_active += 1
                if current_active > max_concurrent_active:
                    max_concurrent_active = current_active
            time.sleep(0.04)
            with lock:
                current_active -= 1
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                content=f"Content of {call.arguments.get('file_path')}",
                is_error=False,
                truncated=False,
            )

        mock_tools.execute.side_effect = mock_execute

        instructions = MagicMock()
        instructions.build.return_value = [{"name": "core", "content": "Help user"}]

        agent_loop = AgentLoop(
            context=ContextBuilder(),
            instructions=instructions,
            tools=mock_tools,
            model=mock_model,
            emit=lambda ev: None,
            workspace=Path("."),
        )

        with patch.dict(os.environ, {"KRATOS_PARALLEL_EXECUTION": "true"}, clear=False):
            final_text, history = agent_loop.run(
                [ChatMessage(role="user", content="Read 3 files")],
                allow_tool=lambda spec, args: (True, "allowed"),
            )

        self.assertIn("Read all 3 files successfully.", final_text)
        # In parallel mode, all 3 workers must be concurrently active at the same time
        self.assertEqual(max_concurrent_active, 3)

    def test_history_order_preserved(self):
        """Ensure tool messages in history strictly match the original tool_calls order even with varying sleep times."""
        calls = [
            ToolCall(name="read_file", arguments={"file_path": "slow.txt"}, call_id="c_slow"),
            ToolCall(name="read_file", arguments={"file_path": "fast.txt"}, call_id="c_fast"),
        ]

        step1_response = ModelResponse(text="", tool_calls=calls, finish_reason="tool_calls")
        step2_response = ModelResponse(text="Done.", tool_calls=[], finish_reason="stop")

        mock_model = MagicMock()
        mock_model.complete.side_effect = [step1_response, step2_response]

        mock_tools = MagicMock()
        mock_tools.schemas.return_value = [{"name": "read_file"}]

        def mock_execute(call, allow_tool=None):
            if call.arguments.get("file_path") == "slow.txt":
                time.sleep(0.05)
                return ToolResult(call_id=call.call_id, name=call.name, content="SLOW RESULT", is_error=False, truncated=False)
            else:
                time.sleep(0.01)
                return ToolResult(call_id=call.call_id, name=call.name, content="FAST RESULT", is_error=False, truncated=False)

        mock_tools.execute.side_effect = mock_execute

        instructions = MagicMock()
        instructions.build.return_value = [{"name": "core", "content": "Help user"}]

        agent_loop = AgentLoop(
            context=ContextBuilder(),
            instructions=instructions,
            tools=mock_tools,
            model=mock_model,
            emit=lambda ev: None,
            workspace=Path("."),
        )

        final_text, history = agent_loop.run(
            [ChatMessage(role="user", content="Read files")],
            allow_tool=lambda spec, args: (True, "allowed"),
        )

        tool_messages = [m for m in history if m.role == "tool"]
        self.assertEqual(len(tool_messages), 2)
        self.assertEqual(tool_messages[0].tool_call_id, "c_slow")
        self.assertEqual(tool_messages[0].content, "SLOW RESULT")
        self.assertEqual(tool_messages[1].tool_call_id, "c_fast")
        self.assertEqual(tool_messages[1].content, "FAST RESULT")

    def test_sequential_mode_when_parallel_disabled(self):
        """When KRATOS_PARALLEL_EXECUTION=false, execute strictly sequentially with max 1 active worker."""
        calls = [
            ToolCall(name="read_file", arguments={"file_path": "f1.txt"}, call_id="1"),
            ToolCall(name="read_file", arguments={"file_path": "f2.txt"}, call_id="2"),
        ]

        step1_response = ModelResponse(text="", tool_calls=calls, finish_reason="tool_calls")
        step2_response = ModelResponse(text="Done.", tool_calls=[], finish_reason="stop")

        mock_model = MagicMock()
        mock_model.complete.side_effect = [step1_response, step2_response]

        mock_tools = MagicMock()
        mock_tools.schemas.return_value = [{"name": "read_file"}]

        execution_order = []
        max_concurrent_active = 0
        current_active = 0
        lock = threading.Lock()

        def mock_execute(call, allow_tool=None):
            nonlocal max_concurrent_active, current_active
            with lock:
                current_active += 1
                if current_active > max_concurrent_active:
                    max_concurrent_active = current_active
            execution_order.append(call.arguments.get("file_path"))
            time.sleep(0.02)
            with lock:
                current_active -= 1
            return ToolResult(call_id=call.call_id, name=call.name, content="OK", is_error=False, truncated=False)

        mock_tools.execute.side_effect = mock_execute

        instructions = MagicMock()
        instructions.build.return_value = [{"name": "core", "content": "Help user"}]

        agent_loop = AgentLoop(
            context=ContextBuilder(),
            instructions=instructions,
            tools=mock_tools,
            model=mock_model,
            emit=lambda ev: None,
            workspace=Path("."),
        )

        with patch.dict(os.environ, {"KRATOS_PARALLEL_EXECUTION": "false"}, clear=False):
            agent_loop.run(
                [ChatMessage(role="user", content="Read")],
                allow_tool=lambda spec, args: (True, "allowed"),
            )

        self.assertEqual(execution_order, ["f1.txt", "f2.txt"])
        self.assertEqual(max_concurrent_active, 1)


class MultiSubagentParallelTests(unittest.TestCase):
    def test_subagent_manager_run_multi_parallel(self):
        max_concurrent_active = 0
        current_active = 0
        lock = threading.Lock()

        def mock_run_isolated(role: str, messages: list) -> str:
            nonlocal max_concurrent_active, current_active
            with lock:
                current_active += 1
                if current_active > max_concurrent_active:
                    max_concurrent_active = current_active
            time.sleep(0.03)
            with lock:
                current_active -= 1
            return f"Report for {role}: completed task successfully"

        manager = SubagentManager(mock_run_isolated)

        specs = [
            {"role": "code_reviewer", "task": "Review PR #42"},
            {"role": "security_auditor", "task": "Audit auth module"},
        ]

        results = manager.run_multi_parallel(specs, max_workers=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].role, "code_reviewer")
        self.assertIn("completed task successfully", results[0].summary)
        self.assertEqual(results[1].role, "security_auditor")
        self.assertIn("completed task successfully", results[1].summary)
        self.assertEqual(max_concurrent_active, 2)

    def test_subagent_manager_handles_exception(self):
        def mock_failing_runner(role: str, messages: list) -> str:
            if role == "faulty":
                raise RuntimeError("Subagent crashed")
            return "OK"

        manager = SubagentManager(mock_failing_runner)
        results = manager.run_multi_parallel([
            {"role": "healthy", "task": "Task 1"},
            {"role": "faulty", "task": "Task 2"},
        ])
        self.assertEqual(len(results), 2)
        self.assertIsNone(results[0].error)
        self.assertEqual(results[0].summary, "OK")
        self.assertEqual(results[1].error, "Subagent crashed")

    def test_spawn_parallel_subagents_tool(self):
        mock_results = [
            SubagentResult(agent_id="1", role="code_reviewer", task="Check styles", summary="No style issues"),
            SubagentResult(agent_id="2", role="tester", task="Run tests", summary="All 10 tests passed"),
        ]
        mock_runner = MagicMock(return_value=mock_results)
        set_parallel_subagent_runner(mock_runner)

        valid_specs = [
            {"role": "code_reviewer", "task": "Check styles"},
            {"role": "tester", "task": "Run tests"},
        ]
        res = spawn_parallel_subagents(valid_specs)
        self.assertIn("Parallel Subagent Execution Report", res)
        self.assertIn("Subagent: `code_reviewer`", res)
        self.assertIn("No style issues", res)
        self.assertIn("Subagent: `tester`", res)
        self.assertIn("All 10 tests passed", res)
        mock_runner.assert_called_once_with(valid_specs)

        # Invalid spec: not a list
        res_invalid = spawn_parallel_subagents("invalid_type")  # type: ignore
        self.assertIn("Error: subagents parameter must be a non-empty list", res_invalid)

        # Invalid spec: empty or missing task
        res_bad_items = spawn_parallel_subagents([{"role": "reviewer"}])
        self.assertIn("Error: No valid subagent tasks found", res_bad_items)

    def test_spawn_parallel_subagents_action_label(self):
        label = format_tool_action_label(
            "spawn_parallel_subagents",
            {"subagents": [{"role": "reviewer"}, {"role": "auditor"}, {"role": "tester"}]},
        )
        self.assertEqual(label, "running 3 subagents in parallel")


if __name__ == "__main__":
    unittest.main()
