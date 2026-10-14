"""The composed runtime captures edits on tool use without delaying conversation."""
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kratos_agent.core.change_review import ChangeReview
from kratos_agent.core.project_memory import ProjectMemory
from kratos_agent.core.runtime_contracts import ToolPermission


def make_runtime(tmp_path, run):
    # Discovery is a separate integration: these checks never start a user's MCPs.
    with patch.dict(os.environ), patch('kratos_agent.core.mcp_runtime.McpManager.discover_enabled', return_value={}):
        from kratos_agent.main import KratosRuntime
    runtime = KratosRuntime.__new__(KratosRuntime)
    runtime.workspace = tmp_path
    runtime.project_memory = ProjectMemory(tmp_path)
    runtime.change_review = ChangeReview(tmp_path)
    runtime._turn_lock = threading.RLock()
    runtime._cancellation_flag = threading.Event()
    runtime._history = []
    runtime.memory = SimpleNamespace(active_session=None, record_turn=Mock())
    runtime.loop = SimpleNamespace(run=run, current_plan=None)
    runtime._check_tool_permission = Mock(return_value=(True, 'authorized'))
    runtime._emit = Mock()
    return runtime


def test_runtime_chat_does_not_scan_workspace(tmp_path):
    runtime = make_runtime(tmp_path, lambda history, *args, **kwargs: ('Hello!', history))
    runtime.change_review.begin = Mock(side_effect=AssertionError('Chat scanned workspace'))
    assert runtime.run_agent('hii') == 'Hello!'
    runtime.change_review.begin.assert_not_called()
    runtime.memory.record_turn.assert_called_once()
    assert runtime.memory.record_turn.call_args.args == ('hii', 'Hello!')
    assert runtime.memory.record_turn.call_args.kwargs['tool_calls'] == []


def test_runtime_tool_captures_existing_user_edits(tmp_path):
    source = tmp_path / 'app.py'
    source.write_text('user edit')
    def run(history, allow, **kwargs):
        allowed, _ = allow(SimpleNamespace(permission=ToolPermission.WRITE, name='write_file'), {'file_path': 'app.py'})
        assert allowed
        source.write_text('agent edit')
        return 'Edited.', history
    runtime = make_runtime(tmp_path, run)
    runtime.run_agent('Fix app.py')
    checkpoint = runtime.change_review.list()[0]
    runtime.change_review.restore(checkpoint['id'], ['app.py'])
    assert source.read_text() == 'user edit'


def test_denied_tool_does_not_start_checkpoint(tmp_path):
    def run(history, allow, **kwargs):
        allowed, _ = allow(SimpleNamespace(permission=ToolPermission.WRITE, name='write_file'), {})
        assert not allowed
        return 'Requires approval.', history
    runtime = make_runtime(tmp_path, run)
    runtime._check_tool_permission.return_value = (False, 'denied')
    runtime.run_agent('Fix app.py')
    assert not runtime.change_review.store.exists()
