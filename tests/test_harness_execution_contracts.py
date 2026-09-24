from pathlib import Path
import ast
import json

ROOT = Path(__file__).resolve().parents[1]


def _function_node(path: Path, name: str):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    return source, next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_parallel_scheduler_batches_safe_perception():
    path = ROOT / "src/kratos_agent/core/agent_loop.py"
    source, node = _function_node(path, "partition_tool_waves")
    class ToolCall:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments
    ns = {
        "List": list,
        "ToolCall": ToolCall,
        "BARRIER_TOOLS": {"run_terminal_command","spawn_parallel_subagents","todo_write","exit_plan_mode","save_memory","clear_memory"},
        "READ_ONLY_TOOLS": {"computer_observe","computer_window_list","read_file"},
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    waves = ns["partition_tool_waves"]([
        ToolCall("computer_observe", {}),
        ToolCall("computer_window_list", {}),
        ToolCall("read_file", {"file_path": "a"}),
    ])
    assert len(waves) == 1
    assert len(waves[0]) == 3


def test_manifest_exposes_verification_and_visual_diagnostics():
    data = json.loads((ROOT/"src/kratos_agent/utils/tools_list.json").read_text(encoding="utf-8"))
    names = {x["name"] for x in data["tools"]}
    assert "verify_project" in names
    assert "computer_visual_diagnose" in names
