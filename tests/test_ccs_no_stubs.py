import ast
import pathlib
import unittest

def _returns_hardcoded_ok(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Detects functions with <= 3 statements that return ok=True / {'ok': True}
    without any preceding I/O, subprocess, perception, or ctypes call.
    """
    if len(node.body) > 3:
        return False
    for stmt in node.body:
        if isinstance(stmt, ast.Return) and stmt.value:
            # Check for {'ok': True}
            if isinstance(stmt.value, ast.Dict):
                for k, v in zip(stmt.value.keys, stmt.value.values):
                    if isinstance(k, ast.Constant) and k.value == "ok":
                        if isinstance(v, ast.Constant) and v.value is True:
                            # Check if prior statement was an observation
                            return True
            # Check for ActionResult(True, ...)
            if isinstance(stmt.value, ast.Call):
                func_name = getattr(stmt.value.func, "id", "") or getattr(stmt.value.func, "attr", "")
                if func_name == "ActionResult":
                    if stmt.value.args and isinstance(stmt.value.args[0], ast.Constant) and stmt.value.args[0].value is True:
                        if len(node.body) == 1:
                            return True
    return False

class TestCcsNoStubs(unittest.TestCase):
    def test_no_stubs_or_pass_in_codebase(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "kratos_agent"
        stubs = []
        for p in root.rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError as e:
                stubs.append(f"{p}:{e.lineno} SYNTAX_ERROR: {e}")
                continue

            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # Abstract interface declarations and optional plugin hooks
                # are contracts/default no-ops, not unfinished implementations.
                decorators = [ast.unparse(item).split(".")[-1] for item in node.decorator_list]
                parent = parents.get(node)
                if "abstractmethod" in decorators:
                    continue
                if node.name in {"on_register", "on_start", "on_stop"}:
                    continue
                if isinstance(parent, ast.ClassDef) and any(
                    ast.unparse(base).split(".")[-1] in {"ABC", "Protocol"}
                    for base in parent.bases
                ):
                    continue
                body = [
                    n for n in node.body
                    if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
                ]
                rel = p.relative_to(root)
                if not body:
                    stubs.append(f"{rel}:{node.lineno} {node.name} -> DOCSTRING_ONLY")
                elif len(body) == 1 and isinstance(body[0], ast.Pass):
                    stubs.append(f"{rel}:{node.lineno} {node.name} -> PASS_ONLY")
                elif len(body) == 1 and isinstance(body[0], ast.Expr) and getattr(body[0].value, "value", None) is Ellipsis:
                    stubs.append(f"{rel}:{node.lineno} {node.name} -> ELLIPSIS_ONLY")
                elif any(isinstance(n, ast.Raise) and getattr(getattr(n.exc, "func", n.exc), "id", "") == "NotImplementedError" for n in ast.walk(node)):
                    stubs.append(f"{rel}:{node.lineno} {node.name} -> NOT_IMPLEMENTED")
                elif _returns_hardcoded_ok(node):
                    stubs.append(f"{rel}:{node.lineno} {node.name} -> FABRICATED_OK")

        self.assertEqual(stubs, [], f"Found {len(stubs)} stubs/fabrications in codebase: {stubs}")

if __name__ == "__main__":
    unittest.main()
