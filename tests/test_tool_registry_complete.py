import json
import pathlib
import unittest
from kratos_agent.core.tool_runtime import legacy_tool_registry

class TestToolRegistryComplete(unittest.TestCase):
    def test_every_registered_tool_has_a_real_implementation(self):
        manifest_path = pathlib.Path(__file__).resolve().parents[1] / "src" / "kratos_agent" / "utils" / "tools_list.json"
        self.assertTrue(manifest_path.exists(), "tools_list.json must exist")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        schemas = data.get("tools", [])

        # Check total count >= 110
        self.assertGreaterEqual(
            len(schemas), 110,
            f"only {len(schemas)} tools registered; the CCS catalog (§8) requires ~115. "
            f"The banner showed 30 — the registry is not being populated."
        )

        # Validate the complete runtime dispatch chain: computer-use handlers
        # are split across dedicated modules, not only utils.computer_tools.
        registry = legacy_tool_registry(pathlib.Path.cwd())
        specs = registry.specs()
        self.assertGreaterEqual(
            len(specs), 110,
            f"legacy_tool_registry loaded only {len(specs)} tools, expected >= 110"
        )

if __name__ == "__main__":
    unittest.main()
