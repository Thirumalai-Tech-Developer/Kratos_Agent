"""Unit test to ensure parallel tool execution does not cause duplicate rendering of the final result."""
import io
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.context_pipeline import ContextBudget, ContextBuilder
from kratos_agent.core.runtime_contracts import (
    ChatMessage,
    ModelResponse,
    ToolCall,
    ToolResult,
)
from kratos_agent.tui.live_renderer import KratosLiveRenderer


class MockToolRegistry:
    def __init__(self):
        self.executed = []

    def schemas(self):
        return [{"name": "read_file"}]

    def execute(self, call: ToolCall, allow_tool=None):
        self.executed.append(call.name)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            content=f"Content of {call.arguments.get('file_path')}",
            is_error=False,
            truncated=False,
        )


class MockInstruction:
    def build(self):
        return [{"name": "core", "content": "Assist user"}]


class ParallelOutputDedupTests(unittest.TestCase):
    def test_eight_parallel_tools_final_result_single_render(self):
        """Simulate 8 parallel tools in a wave followed by a final report; verify no 8x duplication."""
        calls = [
            ToolCall(name="read_file", arguments={"file_path": f"module_{i}.py"}, call_id=f"c_{i}")
            for i in range(8)
        ]

        step1_response = ModelResponse(text="", tool_calls=calls, finish_reason="tool_calls")
        final_text = "### FINAL RECONNAISSANCE REPORT\n" + "Detailed analysis of 8 files completed.\n" * 10
        step2_response = ModelResponse(text=final_text, tool_calls=[], finish_reason="stop")

        class SequentialFakeModel:
            def __init__(self, resps):
                self.resps = list(resps)

            def complete(self, request, on_chunk=None):
                system = str(request.get("system", ""))
                if "kratos execution planner" in system.lower() or "planner-system" in str(request.get("instructions", [])):
                    return ModelResponse(text='{"goal": "Inspect 8 files", "tasks": [{"id": "1", "title": "Inspect files"}]}')
                if self.resps:
                    resp = self.resps.pop(0)
                    if on_chunk and resp.text:
                        on_chunk(resp.text)
                    return resp
                return ModelResponse(text="Done.")

        mock_model = SequentialFakeModel([step1_response, step2_response])

        mock_tools = MockToolRegistry()
        instructions = MockInstruction()

        events_emitted = []

        class MockRuntime:
            def __init__(self):
                self.model_name = "ds-web/deepseek-v4-pro-think"
                self.memory = MagicMock()
                self.memory.active_session = None
                self._emit = events_emitted.append
                self._event_store = MagicMock()
                self._event_store.append = lambda e: None
                self.loop = AgentLoop(
                    context=ContextBuilder(ContextBudget(max_input_tokens=10000)),
                    instructions=instructions,
                    tools=mock_tools,
                    model=mock_model,
                    emit=lambda ev: self._emit(ev),
                    workspace=Path("."),
                )

            def invoke(self, messages):
                history = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
                reply, _ = self.loop.run(history, allow_tool=lambda spec, args: (True, "allowed"))
                return reply

        runtime = MockRuntime()
        out_buf = io.StringIO()
        console = Console(file=out_buf, force_terminal=True, height=25, width=90)

        tui = KratosLiveRenderer(runtime)
        tui._console = console
        tui.live_mode = True
        tui._is_tty = True

        with patch.dict(os.environ, {"KRATOS_PARALLEL_EXECUTION": "true"}, clear=False):
            reply = tui.invoke_with_live([{"role": "user", "content": "inspect 8 files in parallel"}])

        self.assertIn("FINAL RECONNAISSANCE REPORT", reply)
        self.assertEqual(len(mock_tools.executed), 8)

        output_str = out_buf.getvalue()
        # Ensure that during live execution, the final report was not repeatedly dumped into output buffer 8 times
        # With transient=True and vertical_overflow='crop', live buffer clears cleanly upon exit
        final_heading_count = output_str.count("FINAL RECONNAISSANCE REPORT")
        self.assertLessEqual(
            final_heading_count,
            1,
            f"Final report heading was printed {final_heading_count} times in terminal output! Expected <= 1."
        )


if __name__ == "__main__":
    unittest.main()
