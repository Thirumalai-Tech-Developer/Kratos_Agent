import ast
import pathlib
import unittest

class TestNoShellTrue(unittest.TestCase):
    def test_no_forbidden_shell_true(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "kratos_agent"
        violations = []
        for py_path in root.rglob("*.py"):
            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for keyword in node.keywords:
                        if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                            violations.append(f"{py_path.relative_to(root)}:{node.lineno}")

        self.assertEqual(
            violations,
            [],
            f"Forbidden shell=True found in the following files: {violations}. Use argv with shell=False instead."
        )

if __name__ == "__main__":
    unittest.main()
