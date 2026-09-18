"""Unit tests for the autonomous agentic tool calling loop and [tool call] terminal display."""
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kratos_agent.core.agent_loop import AgentLoop, format_tool_action_label, _format_tool_substep
from kratos_agent.core.context_pipeline import ContextBuilder
from kratos_agent.core.provider_runtime import BrainAdapter
from kratos_agent.core.runtime_contracts import ChatMessage, EventKind, ModelResponse, ToolCall, ToolResult
from kratos_agent.core.task_manager import ExecutionPlan


class ToolActionLabelTests(unittest.TestCase):
    def test_read_file_label(self):
        self.assertEqual(format_tool_action_label("read_file", {"file_path": "package.json"}), "inspecting package.json")
        self.assertEqual(format_tool_action_label("read_file", {}), "inspecting file")
        self.assertEqual(_format_tool_substep("read_file", {"file_path": "package.json"}), "[tool call] inspecting package.json")
        self.assertEqual(_format_tool_substep("read_file", {}), "[tool call] inspecting file")

    def test_list_directory_label(self):
        self.assertEqual(format_tool_action_label("list_directory", {"directory_path": "src"}), "inspecting src/")
        self.assertEqual(format_tool_action_label("list_directory", {}), "inspecting directory")

    def test_edit_and_write_file_label(self):
        self.assertEqual(format_tool_action_label("write_file", {"file_path": "main.py"}), "creating main.py")
        self.assertEqual(format_tool_action_label("edit_file", {"file_path": "main.py"}), "updating main.py")

    def test_run_terminal_command_label(self):
        self.assertEqual(format_tool_action_label("run_terminal_command", {"command": "pytest -q"}), "running command pytest -q")

    def test_subagent_and_skill_action_labels(self):
        self.assertEqual(format_tool_action_label("spawn_subagent", {"role": "code_reviewer"}), "delegating to code_reviewer subagent")
        self.assertEqual(_format_tool_substep("spawn_subagent", {"role": "security_auditor"}), "[tool call] delegating to security_auditor subagent")
        self.assertEqual(format_tool_action_label("read_skill", {"skill_name": "frontend-design"}), "reading skill frontend-design")
        self.assertEqual(_format_tool_substep("read_skill", {"skill_name": "api-sec"}), "[tool call] reading skill api-sec")
        self.assertEqual(format_tool_action_label("list_skills", {}), "listing available skills")
        self.assertEqual(_format_tool_substep("list_skills", {}), "[tool call] listing available skills")


class BrainAdapterToolCallingTests(unittest.TestCase):
    def test_adapter_preserves_tool_messages_and_call_ids(self):
        mock_client = MagicMock()
        mock_client.complete.return_value = ("Final response", [])

        adapter = BrainAdapter("gemini-3.7-flash-high", mock_client)

        request = {
            "system": "System instructions",
            "messages": [
                {"role": "user", "content": "What is in config.json?"},
                {
                    "role": "assistant",
                    "content": "call:read_file{\"file_path\": \"config.json\"}",
                    "metadata": {
                        "tool_calls": [
                            {"id": "call_abc123", "name": "read_file", "arguments": {"file_path": "config.json"}}
                        ]
                    }
                },
                {
                    "role": "tool",
                    "content": '{"version": "1.0.0"}',
                    "tool_call_id": "call_abc123",
                    "name": "read_file",
                }
            ],
            "tools": [{"name": "read_file", "parameters": {}}],
        }

        resp = adapter.complete(request)
        self.assertEqual(resp.text, "Final response")

        # Verify client.complete was called with proper messages
        call_args = mock_client.complete.call_args
        self.assertIsNotNone(call_args)
        sent_messages = call_args.kwargs.get("messages") or call_args[1].get("messages")

        # Check assistant turn: content should be None, tool_calls preserved
        assistant_turn = next(m for m in sent_messages if m["role"] == "assistant")
        self.assertIsNone(assistant_turn.get("content"))
        self.assertIn("tool_calls", assistant_turn)
        self.assertEqual(assistant_turn["tool_calls"][0]["id"], "call_abc123")

        # Check tool turn: role="tool", tool_call_id preserved, name preserved
        tool_turn = next(m for m in sent_messages if m["role"] == "tool")
        self.assertEqual(tool_turn["tool_call_id"], "call_abc123")
        self.assertEqual(tool_turn["name"], "read_file")
        self.assertEqual(tool_turn["content"], '{"version": "1.0.0"}')


class AgentLoopToolCallingTests(unittest.TestCase):
    def test_multi_step_tool_loop_execution_and_terminal_events(self):
        # Step 1: model returns tool call to read "secret.txt"
        # Step 2: model returns final text based on tool output
        step1_response = ModelResponse(
            text="",
            tool_calls=[ToolCall(name="read_file", arguments={"file_path": "secret.txt"}, call_id="call_sec99")],
            finish_reason="tool_calls",
        )
        step2_response = ModelResponse(
            text="The secret in the file is OLYMPUS.",
            tool_calls=[],
            finish_reason="stop",
        )

        mock_model = MagicMock()
        mock_model.complete.side_effect = [step1_response, step2_response]

        # Mock tools registry
        mock_tools = MagicMock()
        mock_tools.schemas.return_value = [{"name": "read_file"}]
        mock_tools.execute.return_value = ToolResult(
            call_id="call_sec99",
            name="read_file",
            content="OLYMPUS",
            is_error=False,
            truncated=False,
        )

        emitted_events = []
        def emit_event(ev):
            emitted_events.append(ev)

        instructions = MagicMock()
        instructions.build.return_value = [{"name": "core", "content": "Help user"}]

        workspace = Path(".")
        loop = AgentLoop(
            context=ContextBuilder(),
            instructions=instructions,
            tools=mock_tools,
            model=mock_model,
            emit=emit_event,
            workspace=workspace,
        )

        initial_history = [ChatMessage(role="user", content="What is the secret?")]
        final_text, final_history = loop.run(initial_history, allow_tool=lambda spec, args: (True, "allowed"))

        self.assertIn("The secret in the file is OLYMPUS.", final_text)

        # Verify tool call started event had the required [tool call] display
        tool_start_events = [e for e in emitted_events if e.kind == EventKind.TOOL_CALL_STARTED]
        self.assertEqual(len(tool_start_events), 1)
        payload = tool_start_events[0].payload
        self.assertEqual(payload["name"], "read_file")
        self.assertEqual(payload["call_id"], "call_sec99")
        self.assertEqual(payload["action_label"], "inspecting secret.txt")
        self.assertEqual(payload["display"], "[tool call] inspecting secret.txt")

        # Verify history fed back tool message with call_id and content
        tool_messages = [m for m in final_history if m.role == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].tool_call_id, "call_sec99")
        self.assertEqual(tool_messages[0].name, "read_file")
        self.assertEqual(tool_messages[0].content, "OLYMPUS")

        # Verify model was called twice in the loop
        self.assertEqual(mock_model.complete.call_count, 2)

    def test_casual_capability_query_has_no_plan_and_no_nudges(self):
        # User query "what you can do?" should execute purely as a direct answer without planning
        resp = ModelResponse(
            text="I am Kratos, an autonomous coding agent. I can inspect files, edit code, run terminal commands, and spawn subagents.",
            tool_calls=[],
            finish_reason="stop",
        )
        mock_model = MagicMock()
        mock_model.complete.return_value = resp

        mock_tools = MagicMock()
        mock_tools.schemas.return_value = []

        emitted_events = []
        instructions = MagicMock()
        instructions.build.return_value = [{"name": "test", "layer": "system", "content": "Instructions"}]

        loop = AgentLoop(
            context=ContextBuilder(),
            instructions=instructions,
            tools=mock_tools,
            model=mock_model,
            emit=emitted_events.append,
            workspace=Path("."),
        )

        final_text, history = loop.run(
            [ChatMessage("user", "what you can do?")],
            allow_tool=lambda s, a: (True, "allowed"),
        )

        self.assertIn("autonomous coding agent", final_text)
        self.assertIsNone(loop.current_plan)
        # Ensure no planning started or plan created events were fired
        event_kinds = [e.kind for e in emitted_events]
        self.assertNotIn(EventKind.PLANNING_STARTED, event_kinds)
        self.assertNotIn(EventKind.PLAN_CREATED, event_kinds)
        self.assertIn(EventKind.TURN_COMPLETED, event_kinds)


class DeepSeekToolAndPlanTests(unittest.TestCase):
    def test_dsml_flavor_b_tool_call_extraction(self):
        from kratos_agent.brain.chat_model import extract_tool_calls_from_text
        text = (
            '<｜｜DSML｜｜ calls>\n'
            '<｜｜DSML｜｜ invoke name="run_terminal_command">\n'
            '<｜｜DSML｜｜ parameter name="command" string="true">cd /d "C:\\Users\\thiru\\Documents" && mkdir "ben 10" 2>nul & dir "ben 10"</｜｜DSML｜｜ parameter>\n'
            '</｜｜DSML｜｜ invoke>'
        )
        clean, calls = extract_tool_calls_from_text(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "run_terminal_command")
        self.assertEqual(calls[0]["args"]["command"], 'cd /d "C:\\Users\\thiru\\Documents" && mkdir "ben 10" 2>nul & dir "ben 10"')
        self.assertEqual(clean, "")

    def test_extract_numbered_steps_7_steps(self):
        from kratos_agent.core.planner import extract_numbered_steps
        text = (
            "Here is the execution plan for the Ben 10 website:\n"
            "1. Inspect target workspace and ensure directory structure\n"
            "2. Scaffold React + Vite application with TailwindCSS\n"
            "3. Design Omnitrix interactive hero section and dial controls\n"
            "4. Implement alien roster selection (Heatblast, Four Arms, XLR8, Diamondhead)\n"
            "5. Implement sound effects and alien transformation animations\n"
            "6. Configure responsive layout and sound controls\n"
            "7. Run build verification and validate website in browser"
        )
        steps = extract_numbered_steps(text)
        self.assertIsNotNone(steps)
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[0]["title"], "Inspect target workspace and ensure directory structure")
        self.assertEqual(steps[1]["title"], "Scaffold React + Vite application with TailwindCSS")
        self.assertEqual(steps[6]["title"], "Run build verification and validate website in browser")

    def test_probe_command_does_not_falsely_complete_scaffold_task(self):
        from kratos_agent.core.task_manager import ExecutionPlan, TaskItem, TaskState
        from kratos_agent.core.instruction_engine import InstructionEngine
        from kratos_agent.core.tool_runtime import ToolRegistry, ToolSpec, ToolPermission

        plan = ExecutionPlan(
            goal="Scaffold Ben 10 website",
            tasks=[
                TaskItem(id="1", title="Scaffold React + Vite application and configure TailwindCSS", state=TaskState.PENDING),
                TaskItem(id="2", title="Implement Ben 10 components", state=TaskState.PENDING),
            ]
        )
        # Start task 1
        plan.tasks[0].start()

        # Mock model that runs a probe command: cd /d "..." && mkdir "ben 10" 2>nul & dir "ben 10"
        probe_cmd = 'cd /d "C:\\Users\\thiru\\Documents" && mkdir "ben 10" 2>nul & dir "ben 10"'
        step1 = ModelResponse(
            text="",
            tool_calls=[ToolCall(name="run_terminal_command", arguments={"command": probe_cmd}, call_id="c1")],
            finish_reason="tool_calls",
        )
        step2 = ModelResponse(
            text="Directory ready, now scaffolding.",
            tool_calls=[],
            finish_reason="stop",
        )

        model = MagicMock()
        model.complete.side_effect = [step1, step2, step2, step2]

        tools = ToolRegistry()
        tools.register(
            ToolSpec("run_terminal_command", "run", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, ToolPermission.EXECUTE),
            lambda command: "Volume in drive C has no label.\nDirectory of C:\\Users\\thiru\\Documents\\ben 10\n"
        )

        events = []
        instructions = InstructionEngine()
        loop = AgentLoop(
            context=ContextBuilder(),
            instructions=instructions,
            tools=tools,
            model=model,
            emit=events.append,
            workspace=Path("."),
        )

        loop.current_plan = plan
        # Run one step
        final_text, _ = loop.run([ChatMessage("user", "continue")], allow_tool=lambda s, a: (True, "allowed"), resume_plan=plan)

        # Task 1 must NOT be completed by a probe command like mkdir or dir!
        self.assertNotEqual(plan.tasks[0].state, TaskState.COMPLETED)


class SubagentAndSkillToolsExecutionTests(unittest.TestCase):
    def test_spawn_subagent_with_configured_runner(self):
        from kratos_agent.utils.tools import set_subagent_runner, spawn_subagent
        from kratos_agent.core.subagents import SubagentResult

        mock_runner = MagicMock(return_value=SubagentResult("test_id", "code_reviewer", "Check main.py", "No issues found."))
        set_subagent_runner(mock_runner)

        res = spawn_subagent("code_reviewer", "Check main.py")
        self.assertIn("No issues found", res)
        self.assertIn("Subagent 'code_reviewer' Report", res)
        mock_runner.assert_called_once_with("code_reviewer", "Check main.py")

    def test_spawn_subagent_empty_task(self):
        from kratos_agent.utils.tools import spawn_subagent

        res = spawn_subagent("code_reviewer", "")
        self.assertIn("Error: Subagent task description cannot be empty", res)

    def test_list_skills_execution(self):
        from kratos_agent.utils.tools import list_skills

        out = list_skills()
        self.assertIn("skill(s)", out)
        # Check filtered skills
        out_filtered = list_skills("design")
        self.assertIn("skill(s)", out_filtered)

    def test_read_skill_execution(self):
        from kratos_agent.utils.tools import read_skill

        out = read_skill("frontend-design")
        self.assertIn("SKILL PLAYBOOK", out)
        self.assertIn("frontend-design", out)

    def test_legacy_tool_registry_includes_new_tools(self):
        from kratos_agent.core.tool_runtime import legacy_tool_registry

        registry = legacy_tool_registry(Path("."))
        spec_names = {s.name for s in registry.specs()}
        self.assertIn("spawn_subagent", spec_names)
        self.assertIn("list_skills", spec_names)
        self.assertIn("read_skill", spec_names)


if __name__ == "__main__":
    unittest.main()

