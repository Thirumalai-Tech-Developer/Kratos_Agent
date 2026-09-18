import pathlib
import tempfile
import unittest
from kratos_agent.core.planner import (
    IntentKind,
    classify_intent,
    extract_json_plan,
    formulate_agent_plan,
    should_create_plan,
)
from kratos_agent.core.runtime_contracts import ModelResponse


class MockPlannerModel:
    def __init__(self, plan_json_text: str):
        self.plan_json_text = plan_json_text
        self.recorded_requests = []

    def complete(self, request):
        self.recorded_requests.append(request)
        return ModelResponse(text=self.plan_json_text)


class PlannerTests(unittest.TestCase):
    def test_intent_classification_chat(self):
        self.assertEqual(classify_intent("hello"), IntentKind.CHAT)
        self.assertEqual(classify_intent("hi there!"), IntentKind.CHAT)
        self.assertEqual(classify_intent("how are you?"), IntentKind.CHAT)
        self.assertEqual(classify_intent("who are you"), IntentKind.CHAT)
        self.assertFalse(should_create_plan("hello"))

    def test_intent_classification_questions(self):
        self.assertEqual(classify_intent("what is react?"), IntentKind.QUESTION)
        self.assertEqual(classify_intent("how does OAuth work?"), IntentKind.QUESTION)
        self.assertEqual(classify_intent("explain this function in main.py"), IntentKind.QUESTION)
        self.assertFalse(should_create_plan("what is react?"))

    def test_capability_queries_do_not_trigger_plan(self):
        capabilities_queries = [
            "what you can do?",
            "what can you do?",
            "what do you do?",
            "what can kratos do?",
            "what are your capabilities?",
            "what are your skills",
            "what are your tools",
            "what tools do you have",
            "tell me what you can do",
            "help",
            "help me",
            "can you help me",
            "who are you",
            "list your capabilities",
            "list tools",
            "list skills",
        ]
        for q in capabilities_queries:
            intent = classify_intent(q)
            self.assertIn(
                intent,
                (IntentKind.QUESTION, IntentKind.CHAT),
                f"Query '{q}' was classified as {intent.value} instead of QUESTION/CHAT",
            )
            self.assertFalse(
                should_create_plan(q),
                f"Query '{q}' unexpectedly triggered plan requirement",
            )

    def test_intent_classification_coding_tasks(self):
        self.assertEqual(classify_intent("create a webapp for spiderman"), IntentKind.COMPLEX_AGENT_TASK)
        self.assertEqual(classify_intent("build a 3d solar system in three.js"), IntentKind.COMPLEX_AGENT_TASK)
        self.assertEqual(classify_intent("create a hello world HTML page"), IntentKind.CODING_TASK)
        self.assertEqual(classify_intent("refactor auth module to use jwt"), IntentKind.CODING_TASK)
        self.assertEqual(classify_intent("fix syntax error in script.py"), IntentKind.CODING_TASK)
        self.assertEqual(classify_intent("write a python script to run llm interface with streamlit in interface.py file"), IntentKind.CODING_TASK)
        self.assertTrue(should_create_plan("create a webapp for spiderman"))
        self.assertTrue(should_create_plan("write a python script to run llm interface with streamlit in interface.py file"))

    def test_extract_json_plan_from_markdown_fence(self):
        raw = """Here is the plan:
```json
{
  "goal": "Create Streamlit LLM Interface",
  "tasks": [
    {"id": "1", "title": "Inspect Python project and requirements"},
    {"id": "2", "title": "Implement interface.py with Streamlit and LLM client"},
    {"id": "3", "title": "Verify application startup and interaction"}
  ]
}
```
"""
        parsed = extract_json_plan(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["goal"], "Create Streamlit LLM Interface")
        self.assertEqual(len(parsed["tasks"]), 3)
        self.assertEqual(parsed["tasks"][1]["title"], "Implement interface.py with Streamlit and LLM client")

    def test_agent_generated_plan_streamlit_interface(self):
        mock_output = """{
  "goal": "Write Streamlit LLM Interface in interface.py",
  "tasks": [
    {"id": "1", "title": "Inspect workspace and check dependencies for streamlit and llm provider"},
    {"id": "2", "title": "Design Streamlit chat UI layout and session state handling"},
    {"id": "3", "title": "Implement interface.py with model client integration"},
    {"id": "4", "title": "Verify interface.py syntax and execution"}
  ]
}"""
        model = MockPlannerModel(mock_output)
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)
            plan = formulate_agent_plan(
                "write a python script to run llm interface with streamlit in interface.py file",
                model=model,
                workspace=ws,
            )

            self.assertIsNotNone(plan)
            self.assertEqual(plan.goal, "Write Streamlit LLM Interface in interface.py")
            self.assertEqual(plan.total_count, 4)
            self.assertEqual(plan.tasks[0].title, "Inspect workspace and check dependencies for streamlit and llm provider")
            self.assertEqual(plan.tasks[2].title, "Implement interface.py with model client integration")

    def test_agent_generated_plan_dark_mode(self):
        mock_output = """{
  "goal": "Add Dark Mode to React Application",
  "tasks": [
    {"id": "1", "title": "Inspect React application and CSS styling setup"},
    {"id": "2", "title": "Define dark theme CSS variables and palette"},
    {"id": "3", "title": "Create ThemeToggle component with localStorage persistence"},
    {"id": "4", "title": "Apply dark mode styles across navigation and cards"},
    {"id": "5", "title": "Verify theme toggle behavior and component styling"}
  ]
}"""
        model = MockPlannerModel(mock_output)
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)
            plan = formulate_agent_plan(
                "add dark mode to my existing React application",
                model=model,
                workspace=ws,
            )

            self.assertIsNotNone(plan)
            self.assertEqual(plan.goal, "Add Dark Mode to React Application")
            self.assertEqual(plan.total_count, 5)
            self.assertEqual(plan.tasks[2].title, "Create ThemeToggle component with localStorage persistence")

    def test_dynamic_fallback_plan_distinct_per_request(self):
        # Even on fallback without model response, plans must be distinct and reflect exact prompt
        with tempfile.TemporaryDirectory() as tmp_dir:
            ws = pathlib.Path(tmp_dir)
            # Failing model that raises exception to trigger dynamic fallback
            class FailingModel:
                def complete(self, req):
                    raise RuntimeError("Model offline")

            plan_streamlit = formulate_agent_plan("write a python script with streamlit in interface.py", FailingModel(), ws)
            plan_darkmode = formulate_agent_plan("add dark mode to my app", FailingModel(), ws)
            plan_spiderman = formulate_agent_plan("create a webapp for spiderman", FailingModel(), ws)

            self.assertIn("interface.py", plan_streamlit.tasks[2].title or plan_streamlit.goal)
            self.assertIn("dark mode", plan_darkmode.goal.lower())
            self.assertIn("spider-man", plan_spiderman.goal.lower())

    def test_download_and_play_query_does_not_scaffold_from_scratch(self):
        from kratos_agent.core.planner import dynamic_query_fallback_plan
        plan = dynamic_query_fallback_plan("download mario game and play to complete the game")
        # Goal should not be prefixed with "Implement download"
        self.assertFalse(plan.goal.lower().startswith("implement download"))
        self.assertTrue(plan.goal.lower().startswith("download mario"))

        # Tasks must be operational (acquire/run/play), not scaffolding/architecture
        task_titles = [t.title.lower() for t in plan.tasks]
        self.assertTrue(any("locate and acquire" in t or "acquire" in t for t in task_titles))
        self.assertTrue(any("run" in t or "execute" in t or "automate" in t for t in task_titles))
        self.assertFalse(any("scaffold" in t for t in task_titles))
        self.assertFalse(any("design architecture" in t for t in task_titles))

    def test_natural_language_I_is_not_extracted_as_tool(self):
        from kratos_agent.brain.chat_model import extract_tool_calls_from_text
        text = "I {thought: 'need to download the game'} will now search for it."
        clean, calls = extract_tool_calls_from_text(text)
        tool_names = [c["name"] for c in calls]
        self.assertNotIn("I", tool_names)
        self.assertNotIn("i", tool_names)


if __name__ == "__main__":
    unittest.main()

