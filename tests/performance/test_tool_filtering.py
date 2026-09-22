"""Unit tests for dynamic tool loading and schema filtering."""
from __future__ import annotations
from pathlib import Path
import unittest

from kratos_agent.core.runtime_contracts import ToolPermission, ToolSpec
from kratos_agent.core.tool_runtime import (
    ToolCategory,
    ToolRegistry,
    categorize_tool,
    legacy_tool_registry,
)


class TestToolFiltering(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        # Register sample tools across categories
        self.registry.register(
            ToolSpec("write_file", "Write file", {}, ToolPermission.WRITE),
            lambda **kw: "ok",
        )
        self.registry.register(
            ToolSpec("read_file", "Read file", {}, ToolPermission.READ),
            lambda **kw: "ok",
        )
        self.registry.register(
            ToolSpec("run_terminal_command", "Run command", {}, ToolPermission.EXECUTE),
            lambda **kw: "ok",
        )
        self.registry.register(
            ToolSpec("computer_browser_navigate", "Navigate URL", {}, ToolPermission.NETWORK),
            lambda **kw: "ok",
        )
        self.registry.register(
            ToolSpec("computer_click", "Click element", {}, ToolPermission.EXECUTE),
            lambda **kw: "ok",
        )
        self.registry.register(
            ToolSpec("read_memory", "Read memory", {}, ToolPermission.READ),
            lambda **kw: "ok",
        )
        self.registry.register(
            ToolSpec("todo_write", "Manage tasks", {}, ToolPermission.READ),
            lambda **kw: "ok",
        )

    def test_tool_categorization(self) -> None:
        self.assertEqual(categorize_tool("computer_browser_navigate"), ToolCategory.BROWSER)
        self.assertEqual(categorize_tool("computer_click"), ToolCategory.COMPUTER)
        self.assertEqual(categorize_tool("write_file"), ToolCategory.FILES)
        self.assertEqual(categorize_tool("run_terminal_command"), ToolCategory.CODE)
        self.assertEqual(categorize_tool("read_memory"), ToolCategory.MEMORY)
        self.assertEqual(categorize_tool("todo_write"), ToolCategory.GENERAL)

    def test_dynamic_browser_filtering(self) -> None:
        tools = self.registry.get_tools(context="open youtube and search video in browser")
        names = [t["function"]["name"] for t in tools]

        self.assertIn("computer_browser_navigate", names)
        self.assertIn("computer_click", names)
        self.assertIn("todo_write", names)  # General is always included
        self.assertNotIn("write_file", names)  # Files not relevant
        self.assertNotIn("read_memory", names)

    def test_dynamic_code_filtering(self) -> None:
        tools = self.registry.get_tools(context="run pytest and fix failing tests")
        names = [t["function"]["name"] for t in tools]

        self.assertIn("run_terminal_command", names)
        self.assertIn("write_file", names)
        self.assertIn("todo_write", names)
        self.assertNotIn("computer_browser_navigate", names)

    def test_unfiltered_schemas(self) -> None:
        # Calling schemas without context returns all tools
        all_tools = self.registry.schemas()
        self.assertEqual(len(all_tools), 7)


if __name__ == "__main__":
    unittest.main()
