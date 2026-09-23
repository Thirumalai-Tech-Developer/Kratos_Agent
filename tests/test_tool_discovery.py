"""Unit tests for ToolIndex, ToolSearch, and dynamic 5-15 tool selection."""
import unittest

from kratos_agent.tools.index import ToolIndex, ToolMetadata, get_tool_index
from kratos_agent.tools.discovery import ToolSearch, get_tool_search
from kratos_agent.core.tool_runtime import ToolRegistry, ToolSpec


class TestToolDiscovery(unittest.TestCase):

    def setUp(self):
        self.tool_index = get_tool_index()
        self.tool_search = get_tool_search()

    def test_catalog_index_loaded(self):
        tools = self.tool_index.list_all()
        # Catalog should contain dozens to 180+ tools from tools_list.json
        self.assertGreater(len(tools), 10)

        # Check for core tools
        write_tool = self.tool_index.get("write_file")
        self.assertIsNotNone(write_tool)
        self.assertEqual(write_tool.category, "FILES")

    def test_browser_query_discovers_browser_tools(self):
        query = "Open Chrome and search YouTube for walkthrough"
        results = self.tool_search.search(query, max_results=10)

        # Verify returned count is bounded between 5 and 15
        self.assertGreaterEqual(len(results), 5)
        self.assertLessEqual(len(results), 10)

        # Verify browser-related tools are discovered
        tool_names = [t.name for t in results]
        categories = {t.category for t in results}
        self.assertTrue("BROWSER" in categories or "COMPUTER" in categories)

    def test_coding_query_discovers_code_tools(self):
        query = "Read the python script and edit the function"
        results = self.tool_search.search(query, max_results=10)

        tool_names = [t.name for t in results]
        self.assertTrue(any(k in tool_names for k in ("read_file", "edit_file", "write_file", "grep_search")))

    def test_tool_registry_schemas_dynamic_reduction(self):
        from kratos_agent.core.runtime_contracts import ToolPermission
        reg = ToolRegistry()
        reg.register(ToolSpec(name="browser_navigate", description="Navigate browser tab", parameters={"type": "object"}, permission=ToolPermission.NETWORK), lambda: "ok")
        reg.register(ToolSpec(name="write_file", description="Write code to file", parameters={"type": "object"}, permission=ToolPermission.WRITE), lambda: "ok")
        reg.register(ToolSpec(name="read_file", description="Read code from file", parameters={"type": "object"}, permission=ToolPermission.READ), lambda: "ok")
        reg.register(ToolSpec(name="database_delete", description="Delete database records", parameters={"type": "object"}, permission=ToolPermission.EXECUTE), lambda: "ok")

        # When context is a browser task
        schemas = reg.get_tools(context="Open Chrome and navigate to website", max_tools=5)
        self.assertLessEqual(len(schemas), 5)



if __name__ == "__main__":
    unittest.main()
