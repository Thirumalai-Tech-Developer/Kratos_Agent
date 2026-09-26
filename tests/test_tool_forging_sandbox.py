import os
import shutil
import tempfile
from pathlib import Path
import pytest

from kratos_agent.utils.tool_sandbox import (
    execute_sandboxed_tool,
    log_forged_tool_audit,
    validate_tool_ast,
    verify_tool_in_sandbox,
)
from kratos_agent.utils.tool_creator import create_or_update_tool
from kratos_agent.core.harness.plugins.creator_plugin import CreatorPlugin


def test_static_ast_accepts_benign_code():
    code = """
def reverse_string(text: str = "") -> str:
    return text[::-1]
"""
    valid, err = validate_tool_ast(code, tool_name="reverse_string")
    assert valid is True
    assert err is None


def test_static_ast_rejects_missing_function_name():
    code = """
def other_name(text: str = "") -> str:
    return text
"""
    valid, err = validate_tool_ast(code, tool_name="expected_name")
    assert valid is False
    assert "does not define a function named 'expected_name'" in err


def test_static_ast_rejects_os_system():
    code = """
import os

def malicious_tool(cmd: str = "") -> str:
    os.system("rmdir /s /q test")
    return "done"
"""
    valid, err = validate_tool_ast(code, tool_name="malicious_tool")
    assert valid is False
    assert "os.system" in err or "Forbidden" in err


def test_static_ast_rejects_os_rmdir():
    code = """
import os

def delete_directory(path: str = "") -> str:
    os.rmdir(path)
    return "deleted"
"""
    valid, err = validate_tool_ast(code, tool_name="delete_directory")
    assert valid is False
    assert "os.rmdir" in err or "Forbidden" in err


def test_static_ast_rejects_from_os_import_system():
    code = """
from os import system

def dangerous_tool() -> str:
    system("calc")
    return "ok"
"""
    valid, err = validate_tool_ast(code, tool_name="dangerous_tool")
    assert valid is False
    assert "Forbidden 'os' function import: 'system'" in err


def test_static_ast_rejects_subprocess_when_forbidden():
    code = """
import subprocess

def run_proc() -> str:
    subprocess.run(["dir"], check=False)
    return "ok"
"""
    valid, err = validate_tool_ast(code, tool_name="run_proc", allow_subprocess=False)
    assert valid is False
    assert "subprocess" in err


def test_static_ast_rejects_eval_and_exec():
    code_eval = """
def run_eval(expr: str = "1+1") -> str:
    return str(eval(expr))
"""
    valid, err = validate_tool_ast(code_eval, tool_name="run_eval")
    assert valid is False
    assert "eval" in err

    code_exec = """
def run_exec(stmt: str = "") -> str:
    exec(stmt)
    return "ok"
"""
    valid, err = validate_tool_ast(code_exec, tool_name="run_exec")
    assert valid is False
    assert "exec" in err


def test_static_ast_rejects_subclasses_introspection():
    code = """
def find_subclasses() -> str:
    return str(().__class__.__subclasses__())
"""
    valid, err = validate_tool_ast(code, tool_name="find_subclasses")
    assert valid is False
    assert "__subclasses__" in err


def test_static_ast_rejects_path_traversal():
    code = """
def read_parent_file() -> str:
    path = "../../etc/shadow"
    return path
"""
    valid, err = validate_tool_ast(code, tool_name="read_parent_file")
    assert valid is False
    assert "Forbidden path traversal sequence" in err


def test_sandboxed_execution_benign_tool():
    code = """
def reverse_string(text: str = "") -> str:
    return text[::-1]
"""
    res = execute_sandboxed_tool(code, "reverse_string", kwargs={"text": "kratos"})
    assert res["success"] is True
    assert res["result"] == "sotark"


def test_sandboxed_execution_timeout():
    code = """
def infinite_loop() -> str:
    while True:
        pass
    return "done"
"""
    res = execute_sandboxed_tool(code, "infinite_loop", timeout=1.0)
    assert res["success"] is False
    assert "timed out" in res["error"].lower()


def test_sandboxed_execution_env_stripped():
    os.environ["OPENAI_API_KEY"] = "sk-secret-test-key-should-be-stripped"
    os.environ["KRATOS_SECRET_TOKEN"] = "super-secret-token"

    code = """
import os

def check_env() -> str:
    leaks = [k for k in os.environ if "SECRET" in k or "API_KEY" in k]
    return ",".join(leaks)
"""
    res = execute_sandboxed_tool(code, "check_env")
    assert res["success"] is True
    assert res["result"] == ""


def test_verify_tool_in_sandbox_pass():
    code = """
def multiply_nums(a: int = 1, b: int = 2) -> str:
    return str(a * b)
"""
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"}
        }
    }
    verified, err = verify_tool_in_sandbox(code, "multiply_nums", schema)
    assert verified is True
    assert err is None


def test_verify_tool_in_sandbox_fail_on_runtime_error():
    code = """
def buggy_tool(x: str = "") -> str:
    raise ValueError("Intentional crash during tool execution")
"""
    verified, err = verify_tool_in_sandbox(code, "buggy_tool")
    assert verified is False
    assert "Intentional crash" in err


def test_audit_log_creation(tmp_path):
    code = """
def greet(name: str = "world") -> str:
    return f"hello {name}"
"""
    audit_file = log_forged_tool_audit(
        tool_name="greet",
        code=code,
        author_model="gemma-4",
        trigger_prompt="Create a greeting tool",
        workspace=tmp_path,
    )

    assert audit_file.exists()
    content = audit_file.read_text(encoding="utf-8")
    assert "KRATOS FORGED TOOL AUDIT LOG" in content
    assert "Tool Name: greet" in content
    assert "Author Model: gemma-4" in content
    assert "Trigger Prompt: Create a greeting tool" in content
    assert "Source SHA-256:" in content
    assert "def greet(name: str = \"world\")" in content


def test_create_or_update_tool_rejection_of_malicious_code(monkeypatch):
    monkeypatch.setenv("KRATOS_ALLOW_DYNAMIC_PLUGINS", "true")

    malicious_code = """
import os

def rmdir_tool(path: str = "") -> str:
    os.rmdir(path)
    return "deleted"
"""
    result = create_or_update_tool(
        tool_name="rmdir_tool",
        description="Malicious tool attempting rmdir",
        python_code=malicious_code,
    )

    assert "Static analysis security rejection" in result
    assert "os.rmdir" in result or "Forbidden" in result


def test_create_or_update_tool_benign_success_and_execution(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("KRATOS_ALLOW_DYNAMIC_PLUGINS", "true")
    fake_tools_py = tmp_path / "fake_tools.py"
    fake_tools_py.write_text("# Initial tools\n", encoding="utf-8")
    fake_tools_json = tmp_path / "fake_tools.json"
    fake_tools_json.write_text('{"tools": []}', encoding="utf-8")

    import kratos_agent.utils.tool_creator as tc
    monkeypatch.setattr(tc, "TOOLS_PY_PATH", fake_tools_py)
    monkeypatch.setattr(tc, "TOOLS_JSON_PATH", fake_tools_json)

    benign_code = """
def reverse_string(text: str = "") -> str:
    return text[::-1]
"""
    result = tc.create_or_update_tool(
        tool_name="reverse_string",
        description="Reverses an input string",
        python_code=benign_code,
        parameters_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        author_model="test-model",
        trigger_prompt="reverse-string: Reverses an input string",
        workspace=tmp_path,
    )

    assert "successfully created" in result.lower()

    # Verify audit file was created
    audit_files = list((tmp_path / ".kratos" / "forged_tools").glob("reverse_string_*.py"))
    assert len(audit_files) == 1
    assert "reverse-string: Reverses an input string" in audit_files[0].read_text(encoding="utf-8")

    # Verify tools.py content has sandboxed wrapper
    written_py = fake_tools_py.read_text(encoding="utf-8")
    assert "def reverse_string(*args, **kwargs)" in written_py
    assert "execute_sandboxed_tool" in written_py

    # Verify tools_list.json was updated
    tools_data = json.loads(fake_tools_json.read_text(encoding="utf-8"))
    assert any(t["name"] == "reverse_string" for t in tools_data["tools"])


def test_creator_plugin_validate_plugin_code_rejects_malicious_code():
    plugin = CreatorPlugin()

    malicious_source = """
import os
from kratos_agent.core.harness.plugin import HarnessPlugin, PluginMetadata

class EvilPlugin(HarnessPlugin):
    def __init__(self):
        super().__init__(PluginMetadata(name="evil", version="1.0.0", description="evil"))

    def on_enable(self):
        os.system("echo hacked")
"""
    valid, err = plugin.validate_plugin_code(malicious_source)
    assert valid is False
    assert "Static analysis security rejection" in err
