import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from kratos_agent.core.agent_loop import AgentLoop
from kratos_agent.core.execution_control import collect_command_output, execution_scope, stop_process_tree
from kratos_agent.core.runtime_contracts import ToolCall


def spawn(code):
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def test_stop_interrupts_silent_command_without_stopping_other_processes():
    owned = spawn("import time; time.sleep(30)")
    unrelated = spawn("import time; time.sleep(30)")
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    started = time.monotonic()
    timer.start()
    try:
        with execution_scope(cancel), pytest.raises(InterruptedError):
            collect_command_output(owned)
        assert time.monotonic() - started < 5
        assert owned.poll() is not None
        assert unrelated.poll() is None
    finally:
        timer.cancel()
        stop_process_tree(owned)
        stop_process_tree(unrelated)
        for process in (owned, unrelated):
            process.stdout.close()


def test_timeout_applies_before_silent_command_emits_output():
    process = spawn("import time; time.sleep(30)")
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            collect_command_output(process, timeout=0.2)
        assert process.poll() is not None
    finally:
        stop_process_tree(process)
        process.stdout.close()


def test_cancelled_worker_never_runs_next_tool(tmp_path):
    cancel = threading.Event()
    tools = MagicMock()
    loop = AgentLoop(MagicMock(), MagicMock(), tools, MagicMock(), lambda event: None,
                     tmp_path, cancel)
    cancel.set()
    result = loop._execute_tool_call_worker(ToolCall("write_file", {"file_path": "app.py"}), lambda *args: (True, "allowed"))
    tools.execute.assert_not_called()
    assert result.is_error and "Cancelled" in result.content
