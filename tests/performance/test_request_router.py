"""Unit tests for RequestRouter and Fast Path classification."""
from __future__ import annotations
import unittest

from kratos_agent.performance.router import RequestCategory, RequestRouter


class TestRequestRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RequestRouter()

    def test_math_fast_path(self) -> None:
        decision = self.router.classify("What is 2+2?")
        self.assertEqual(decision.category, RequestCategory.CHAT)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)
        self.assertFalse(decision.requires_observation)

    def test_greeting_fast_path(self) -> None:
        decision = self.router.classify("Hello Kratos!")
        self.assertEqual(decision.category, RequestCategory.CHAT)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)

    def test_code_generation_fast_path(self) -> None:
        decision = self.router.classify("Write a python function to compute fibonacci")
        self.assertEqual(decision.category, RequestCategory.CODE)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)
        self.assertIn("CODE", decision.target_tool_categories)

    def test_single_tool_execution(self) -> None:
        decision = self.router.classify("Run pytest")
        self.assertEqual(decision.category, RequestCategory.TOOL)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)
        self.assertEqual(decision.direct_tool, "run_terminal_command")

    def test_git_status_tool(self) -> None:
        decision = self.router.classify("git status")
        self.assertEqual(decision.category, RequestCategory.TOOL)
        self.assertTrue(decision.is_fast_path)
        self.assertEqual(decision.direct_tool, "git_status")

    def test_simple_computer_use(self) -> None:
        decision = self.router.classify("Open Chrome")
        self.assertEqual(decision.category, RequestCategory.COMPUTER_USE)
        self.assertTrue(decision.is_fast_path)
        self.assertFalse(decision.requires_planning)
        self.assertTrue(decision.requires_observation)
        self.assertIn("BROWSER", decision.target_tool_categories)

    def test_complex_multi_step_task(self) -> None:
        decision = self.router.classify("Open Chrome and search for God of War on YouTube and play it")
        self.assertEqual(decision.category, RequestCategory.COMPLEX_TASK)
        self.assertFalse(decision.is_fast_path)
        self.assertTrue(decision.requires_planning)
        self.assertTrue(decision.requires_observation)

    def test_memory_query(self) -> None:
        decision = self.router.classify("What do you remember about my preferences?")
        self.assertEqual(decision.category, RequestCategory.MEMORY_QUERY)
        self.assertTrue(decision.is_fast_path)
        self.assertTrue(decision.requires_memory)
        self.assertIn("MEMORY", decision.target_tool_categories)


if __name__ == "__main__":
    unittest.main()
