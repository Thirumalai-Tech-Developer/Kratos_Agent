import tempfile
import unittest
from pathlib import Path

from kratos_agent.core.runtime_contracts import ModelResponse, ToolCall
from kratos_agent.main import KratosRuntime
from kratos_agent.tui.live_renderer import KratosLiveRenderer


class LiveRendererWiringTests(unittest.TestCase):
    def test_live_renderer_receives_plan_and_tool_events(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = Path(tmp_dir)
            runtime = KratosRuntime(workspace=ws, model_name="gemini-3.7-flash-high")

            # Mock model returning tool calls then final text
            responses = [
                ModelResponse(
                    tool_calls=[ToolCall("write_file", {"file_path": "index.html", "content": "<h1>Spider-Man</h1>"})]
                ),
                ModelResponse(text="Successfully implemented Spider-Man application."),
            ]

            class SequentialFakeModel:
                def __init__(self, resps):
                    self.resps = list(resps)

                def complete(self, request):
                    system = request.get("system", "")
                    if "Kratos Planner" in system:
                        return ModelResponse(text='{"goal": "Create a Spider-Man web application", "tasks": [{"id": "1", "title": "Inspect project"}, {"id": "2", "title": "Implement Spider-Man UI"}]}')
                    if self.resps:
                        return self.resps.pop(0)
                    return ModelResponse(text="Done.")

            runtime.loop.model = SequentialFakeModel(responses)

            tui = KratosLiveRenderer(runtime)
            tui.live_mode = False  # Synchronous plain mode for testing event capture

            import os
            prev_cwd = os.getcwd()
            os.chdir(ws)
            try:
                reply = tui.invoke_with_live([{"role": "user", "content": "create a webapp for spiderman"}])
            finally:
                os.chdir(prev_cwd)



            # Verify plan was captured by renderer
            plan = tui.get_last_plan()
            self.assertIsNotNone(plan, "ExecutionPlan must be captured by KratosLiveRenderer!")
            self.assertEqual(plan.goal, "Create a Spider-Man web application")
            self.assertGreater(plan.total_count, 0)
            self.assertEqual(plan.completed_count, plan.total_count)

            # Verify steps recorded
            events = tui.get_last_events()
            event_kinds = [e.get("kind") for e in events]
            self.assertIn("plan.created", event_kinds)
            self.assertIn("task.started", event_kinds)
            self.assertIn("tool.started", event_kinds)
            self.assertIn("verification.started", event_kinds)
            self.assertIn("agent.completed", event_kinds)


if __name__ == "__main__":
    unittest.main()
