import json
import pathlib
import unittest
from kratos_agent.core.tool_runtime import legacy_tool_registry
from kratos_agent.utils import tools as legacy
from kratos_agent.utils import computer_tools

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

        # Collect implementations
        missing = []
        for s in schemas:
            fname = s.get("func_name", s.get("name"))
            h_legacy = getattr(legacy, fname, None)
            h_comp = getattr(computer_tools, fname, None)
            if h_legacy is None and h_comp is None:
                missing.append(s["name"])

        self.assertEqual(missing, [], f"{len(missing)} tools have a schema but no impl: {missing}")

        # Test legacy_tool_registry() loads them all
        registry = legacy_tool_registry(pathlib.Path.cwd())
        specs = registry.specs()
        self.assertGreaterEqual(
            len(specs), 110,
            f"legacy_tool_registry loaded only {len(specs)} tools, expected >= 110"
        )

if __name__ == "__main__":
    unittest.main()
