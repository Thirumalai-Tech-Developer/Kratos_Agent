"""Regression tests for the deterministic Live/mission harness contracts.

These tests intentionally use only the Python standard library so they can run in
minimal CI environments and catch protocol regressions before importing optional
Gemini/desktop dependencies.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "src" / "kratos_agent" / "live" / "session.py"
BRIDGE = ROOT / "src" / "kratos_agent" / "live" / "bridge.py"
SUPERVISOR = ROOT / "src" / "kratos_agent" / "master" / "supervisor.py"
ROUTER = ROOT / "src" / "kratos_agent" / "live" / "router.py"
RUNTIME = ROOT / "src" / "kratos_agent" / "live" / "runtime.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    return ast.get_source_segment(source, node) or ""


def test_receive_loop_never_blocks_on_live_tool_execution():
    source = _function_source(SESSION, "receive_loop")
    assert "await self.router.handle_tool_call" not in source
    assert "asyncio.create_task(" in source
    assert "self._track_tool_task(" in source


def test_extended_thinking_does_not_use_turn_complete_as_idle_signal():
    source = _function_source(SESSION, "receive_loop")
    assert "not self._requires_interaction_status()" in source
    assert "interaction_status == \"IDLE\"" in source


def test_mission_result_is_forwarded_and_waited_for():
    bridge = _function_source(BRIDGE, "submit_task")
    supervisor = _function_source(SUPERVISOR, "submit_delegated_task")
    assert "wait_for_result=wait_for_result" in bridge
    assert "await result_task" in supervisor
    assert "emit_speech=not wait_for_result" in supervisor


def test_live_router_exposes_non_blocking_tools():
    source = _function_source(ROUTER, "get_tool_declarations")
    assert source.count('behavior="NON_BLOCKING"') >= 7
    assert "returned result is authoritative" in source.lower()


def test_session_stops_pending_tool_tasks_cleanly():
    source = _function_source(SESSION, "stop")
    assert "self._pending_tool_tasks" in source
    assert "self._pending_mission_tool_ids.clear()" in source


def test_runtime_wires_live_diagnostics_into_status_tool():
    source = RUNTIME.read_text(encoding="utf-8")
    assert "self.router.set_diagnostics_handler(self.session.get_diagnostics)" in source
