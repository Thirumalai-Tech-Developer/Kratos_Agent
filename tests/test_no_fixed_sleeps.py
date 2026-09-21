import ast
import pathlib
import unittest

class TestNoFixedSleeps(unittest.TestCase):
    def test_no_constant_sleeps_in_ccs(self):
        """AST check banning time.sleep(constant) and asyncio.sleep(constant) in ccs/**.
        All waits must be condition polls with deadlines.
        """
        ccs_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "kratos_agent" / "ccs"
        violations = []

        for py_path in ccs_dir.rglob("*.py"):
            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Check if func is time.sleep or asyncio.sleep
                    is_sleep = False
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "sleep":
                        if isinstance(node.func.value, ast.Name) and node.func.value.id in ("time", "asyncio"):
                            is_sleep = True

                    if is_sleep and node.args:
                        arg = node.args[0]
                        # Flag if argument is a literal constant (e.g. time.sleep(1), time.sleep(0.5))
                        if isinstance(arg, ast.Constant):
                            violations.append(f"{py_path.relative_to(ccs_dir)}:{node.lineno} sleep({arg.value})")

        self.assertEqual(
            violations,
            [],
            f"Fixed time.sleep(constant) found in ccs: {violations}. Replace with condition polling."
        )

if __name__ == "__main__":
    unittest.main()
