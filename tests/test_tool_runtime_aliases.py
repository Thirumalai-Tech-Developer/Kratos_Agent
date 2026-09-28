"""Unit tests for tool runtime aliasing, argument normalization, and schema priority."""
from __future__ import annotations

import unittest
from pathlib import Path

from kratos_agent.core.runtime_contracts import ToolCall
from kratos_agent.core.tool_runtime import TOOL_ALIASES, ToolCategory, legacy_tool_registry
from kratos_agent.performance.router import RequestCategory, get_request_router


class TestToolRuntimeAliases(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(".").resolve()
        self.registry = legacy_tool_registry(self.workspace)
        self.allow_all = lambda spec, args: (True, "")

    def test_terminal_aliases_resolve(self) -> None:
        aliases = [
            ("terminal", {"command": "Write-Output 'terminal_ok'"}),
            ("terminal_run_command", {"cmd": "Write-Output 'terminal_run_cmd_ok'"}),
            ("run_terminal_cmd", {"terminal_command": "Write-Output 'run_term_cmd_ok'"}),
            ("run_command", {"script": "Write-Output 'run_cmd_ok'"}),
            ("cmd", {"command": "Write-Output 'cmd_ok'"}),
            ("powershell", {"command": "Write-Output 'ps_ok'"}),
        ]
        for name, args in aliases:
            call = ToolCall(name=name, arguments=args)
            result = self.registry.execute(call, self.allow_all)
            self.assertFalse(
                result.is_error and "Unknown tool" in result.content,
                f"Tool alias '{name}' was not recognized: {result.content}",
            )
            self.assertEqual(call.name, "run_terminal_command")

    def test_file_tool_aliases_and_arg_normalization(self) -> None:
        test_file = self.workspace / "test_alias_dummy.txt"
        try:
            # create_file alias with path + text args
            call1 = ToolCall(name="create_file", arguments={"path": str(test_file), "text": "hello alias"})
            res1 = self.registry.execute(call1, self.allow_all)
            self.assertFalse(res1.is_error, res1.content)
            self.assertEqual(call1.name, "write_file")
            self.assertTrue(test_file.exists())

            # read_file alias with path arg
            call2 = ToolCall(name="view_file", arguments={"path": str(test_file)})
            res2 = self.registry.execute(call2, self.allow_all)
            self.assertFalse(res2.is_error, res2.content)
            self.assertEqual(call2.name, "read_file")
            self.assertIn("hello alias", res2.content)

            # edit_file alias with file + find + replace args
            call3 = ToolCall(name="modify_file", arguments={"file": str(test_file), "find": "hello alias", "replace": "updated alias"})
            res3 = self.registry.execute(call3, self.allow_all)
            self.assertFalse(res3.is_error, res3.content)
            self.assertEqual(call3.name, "edit_file")

            # directory alias with folder arg
            call4 = ToolCall(name="list_dir", arguments={"folder": str(self.workspace)})
            res4 = self.registry.execute(call4, self.allow_all)
            self.assertFalse(res4.is_error, res4.content)
            self.assertEqual(call4.name, "list_directory")
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_dev_creation_prompt_receives_essential_tools(self) -> None:
        prompt = "make a Dragon Ball Web site using React+TailwindCSS in Documents Folder named in DBZ"
        router = get_request_router()
        decision = router.classify(prompt)

        self.assertEqual(decision.category, RequestCategory.COMPLEX_TASK)
        self.assertIn("CODE", decision.target_tool_categories)
        self.assertIn("FILES", decision.target_tool_categories)
        self.assertIn("SYSTEM", decision.target_tool_categories)

        tools = self.registry.schemas(categories=decision.target_tool_categories, context=prompt)
        names = [t["function"]["name"] for t in tools]

        self.assertIn("run_terminal_command", names)
        self.assertIn("write_file", names)
        self.assertIn("edit_file", names)
        self.assertIn("read_file", names)
        self.assertIn("list_directory", names)
        self.assertIn("grep_search", names)


if __name__ == "__main__":
    unittest.main()
