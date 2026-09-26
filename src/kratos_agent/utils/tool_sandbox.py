"""Kratos Tool Sandbox - Static Analysis, Subprocess Isolation, and Audit Logging.

This module sandboxes autonomous tool forging:
1. Static AST validation (rejection of dangerous calls, imports, and path traversals)
2. Subprocess execution with stripped credentials, tempdir isolation, and timeouts
3. Sandbox verification testing before tool registration
4. Audit logging of forged tools to .kratos/forged_tools/
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Runner script passed to isolated python subprocess
_RUNNER_SCRIPT = r"""
import sys
import json
import traceback

def main():
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input)
        code = payload["code"]
        func_name = payload["func_name"]
        args = payload.get("args", [])
        kwargs = payload.get("kwargs", {})

        namespace = {}
        compiled = compile(code, f"<sandboxed_{func_name}>", "exec")
        exec(compiled, namespace)

        if func_name not in namespace:
            sys.stdout.write(json.dumps({
                "success": False,
                "error": f"Function '{func_name}' not defined in tool code."
            }))
            return

        fn = namespace[func_name]
        result = fn(*args, **kwargs)
        sys.stdout.write(json.dumps({"success": True, "result": result}))
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "success": False,
            "error": f"{type(exc).__name__}: {str(exc)}",
            "traceback": traceback.format_exc(),
        }))

if __name__ == "__main__":
    main()
"""


class ToolSecurityVisitor(ast.NodeVisitor):
    """AST visitor enforcing security policies on forged tool source code."""

    def __init__(self, allow_subprocess: bool = False):
        self.allow_subprocess = allow_subprocess
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in {"subprocess", "pty", "commands", "ctypes", "socket"}:
                if root == "subprocess" and self.allow_subprocess:
                    continue
                self.errors.append(f"Forbidden module import: '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        mod_root = mod.split(".")[0]
        if mod_root in {"subprocess", "pty", "commands", "ctypes", "socket"}:
            if mod_root == "subprocess" and self.allow_subprocess:
                pass
            else:
                self.errors.append(f"Forbidden module import from '{mod}'")

        if mod_root == "os":
            forbidden_os = {
                "system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe",
                "spawnv", "spawnve", "spawnvp", "spawnvpe", "execv", "execve",
                "execvp", "execvpe", "remove", "unlink", "rmdir", "removedirs",
                "chmod", "chown", "kill", "killpg"
            }
            for alias in node.names:
                if alias.name in forbidden_os:
                    self.errors.append(f"Forbidden 'os' function import: '{alias.name}'")

        if mod_root == "shutil":
            for alias in node.names:
                if alias.name in {"rmtree", "move"}:
                    self.errors.append(f"Forbidden 'shutil' function import: '{alias.name}'")

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "compile", "__import__", "globals", "locals"}:
                self.errors.append(f"Forbidden call to built-in function: '{node.func.id}()'")
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in {"system", "popen", "rmdir", "removedirs", "remove", "unlink", "chmod", "chown", "kill"}:
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    self.errors.append(f"Forbidden call: 'os.{attr}()'")
            if not self.allow_subprocess and attr in {"run", "Popen", "call", "check_call", "check_output"}:
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                    self.errors.append(f"Forbidden call: 'subprocess.{attr}()'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in {"__subclasses__", "__globals__", "__code__", "__bases__", "__mro__", "__builtins__"}:
            self.errors.append(f"Forbidden introspection attribute access: '{node.attr}'")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            val = node.value
            if ".." in val and ("/" in val or "\\" in val):
                self.errors.append(f"Forbidden path traversal sequence in string literal: '{val}'")
            if val.startswith(("/etc", "/root", "/bin", "/sbin", "/usr", "C:\\Windows", "C:\\Program Files")):
                self.errors.append(f"Forbidden system root path access in string literal: '{val}'")
        self.generic_visit(node)


def validate_tool_ast(
    code: str,
    tool_name: str | None = None,
    allow_subprocess: bool = False,
) -> tuple[bool, str | None]:
    """Statically validate tool Python code using AST security policies."""
    try:
        parsed_ast = ast.parse(code)
    except SyntaxError as e:
        return False, f"Python syntax validation failed on line {e.lineno}: {e.msg}"

    if tool_name:
        defined_funcs = [
            node.name for node in ast.walk(parsed_ast)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if tool_name not in defined_funcs:
            return False, (
                f"Provided python_code does not define a function named '{tool_name}'. "
                f"Found functions: {defined_funcs}"
            )

    visitor = ToolSecurityVisitor(allow_subprocess=allow_subprocess)
    visitor.visit(parsed_ast)

    if visitor.errors:
        return False, "; ".join(visitor.errors)

    return True, None


def _get_stripped_environment() -> dict[str, str]:
    """Build a minimal environment dictionary stripped of secrets and tokens."""
    safe_keys = {
        "SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TMP", "TEMP", "USERPROFILE",
        "HOME", "TMPDIR", "PYTHONPATH", "PYTHONUTF8", "PYTHONIOENCODING", "LANG", "LC_ALL"
    }
    forbidden_substrings = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "API", "CRED")
    forbidden_prefixes = ("KRATOS_", "OPENAI_", "ANTHROPIC_", "GEMINI_", "DEEPSEEK_", "AWS_", "CLOUDFLARE_")

    stripped: dict[str, str] = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if any(substr in k_upper for substr in forbidden_substrings):
            continue
        if any(k_upper.startswith(prefix) for prefix in forbidden_prefixes):
            continue
        if k_upper in safe_keys:
            stripped[k] = v

    stripped["PYTHONUTF8"] = "1"
    stripped["PYTHONIOENCODING"] = "utf-8"
    return stripped


def execute_sandboxed_tool(
    code: str,
    func_name: str,
    kwargs: dict[str, Any] | None = None,
    args: list[Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Execute a forged tool function in an isolated subprocess with stripped env and resource bounds."""
    payload = {
        "code": code,
        "func_name": func_name,
        "args": args or [],
        "kwargs": kwargs or {},
    }

    env = _get_stripped_environment()

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _RUNNER_SCRIPT],
                input=json.dumps(payload),
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Tool execution timed out after {timeout:.1f}s",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": f"Subprocess launch failed: {exc}",
            }

        stdout = proc.stdout.strip()
        if stdout:
            try:
                res = json.loads(stdout)
                if isinstance(res, dict) and "success" in res:
                    return res
            except json.JSONDecodeError:
                pass

        if proc.returncode != 0:
            err = proc.stderr.strip() or f"Process exited with code {proc.returncode}"
            return {"success": False, "error": err}

        return {"success": True, "result": stdout}


def generate_test_arguments(
    schema: dict[str, Any] | None,
    code: str,
    tool_name: str,
) -> dict[str, Any]:
    """Derive sensible mock arguments from parameter schema or AST for verification."""
    test_args: dict[str, Any] = {}
    if schema and isinstance(schema.get("properties"), dict):
        props = schema["properties"]
        for prop_name, prop_spec in props.items():
            prop_type = prop_spec.get("type", "string") if isinstance(prop_spec, dict) else "string"
            if prop_type in ("string", "str"):
                test_args[prop_name] = "test"
            elif prop_type in ("integer", "number", "int", "float"):
                test_args[prop_name] = 1
            elif prop_type in ("boolean", "bool"):
                test_args[prop_name] = True
            elif prop_type in ("array", "list"):
                test_args[prop_name] = []
            elif prop_type in ("object", "dict"):
                test_args[prop_name] = {}
            else:
                test_args[prop_name] = "test"
    else:
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == tool_name:
                    for arg in node.args.args:
                        if arg.arg != "self":
                            test_args[arg.arg] = "test"
                    break
        except Exception:
            pass

    return test_args


def verify_tool_in_sandbox(
    code: str,
    tool_name: str,
    parameters_schema: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> tuple[bool, str | None]:
    """Run an automated verification smoke test against the tool in the sandbox."""
    test_args = generate_test_arguments(parameters_schema, code, tool_name)
    res = execute_sandboxed_tool(
        code=code,
        func_name=tool_name,
        kwargs=test_args,
        timeout=timeout,
    )
    if res.get("success"):
        return True, None
    return False, str(res.get("error", "Unknown test failure"))


def log_forged_tool_audit(
    tool_name: str,
    code: str,
    author_model: str = "kratos",
    trigger_prompt: str = "",
    workspace: Path | None = None,
) -> Path:
    """Persist an immutable audit record for the forged tool in .kratos/forged_tools/."""
    base_dir = (workspace or Path.cwd()) / ".kratos" / "forged_tools"
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()

    header = (
        f"# ==============================================================================\n"
        f"# KRATOS FORGED TOOL AUDIT LOG\n"
        f"# Tool Name: {tool_name}\n"
        f"# Timestamp (UTC): {timestamp}\n"
        f"# Author Model: {author_model}\n"
        f"# Source SHA-256: {sha256}\n"
        f"# Trigger Prompt: {trigger_prompt.strip()}\n"
        f"# ==============================================================================\n\n"
    )

    audit_file = base_dir / f"{tool_name}_{timestamp}.py"
    audit_file.write_text(header + code.strip() + "\n", encoding="utf-8")
    return audit_file
