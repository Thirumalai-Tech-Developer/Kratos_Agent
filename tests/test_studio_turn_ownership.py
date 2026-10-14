"""Session activation belongs to the thread executing the protected runtime turn."""
import json
import threading
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from test_studio_web import call, server as shared_server

from kratos_agent.web.server import KratosWebHandler

server = shared_server


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/sync"])
def test_browser_turn_cannot_switch_a_voice_turns_session(server, path):
    runtime = server.runtime
    runtime._turn_lock = threading.RLock()
    runtime.memory.load_session = Mock()
    runtime.activate_session = Mock()
    runtime.clear_cancel = Mock()
    runtime._turn_lock.acquire()
    try:
        with pytest.raises(HTTPError) as failure:
            call(server, path, {"prompt": "continue", "session_id": "other"})
        assert failure.value.code == 409
        assert runtime.memory.active_session.session_id == "test-session"
        runtime.memory.load_session.assert_not_called()
        runtime.activate_session.assert_not_called()
        runtime.clear_cancel.assert_not_called()
        runtime.run_agent.assert_not_called()
    finally:
        runtime._turn_lock.release()


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/sync"])
def test_requested_session_activates_under_runtime_lock(server, path):
    runtime = server.runtime
    runtime._turn_lock = threading.RLock()
    runtime.memory.load_session = Mock(return_value=True)
    runtime.activate_session = Mock(side_effect=lambda: assert_owned(runtime))
    runtime.run_agent.side_effect = lambda *args, **kwargs: assert_owned(runtime) or "verified result"
    with call(server, path, {"prompt": "continue", "session_id": "test-session"}) as response:
        response.read()
    runtime.activate_session.assert_called_once()
    runtime.run_agent.assert_called_once()
    assert runtime._turn_lock.acquire(timeout=2)
    runtime._turn_lock.release()


def assert_owned(runtime):
    assert runtime._turn_lock._is_owned()


def test_stream_preserves_stop_received_after_headers(server, monkeypatch):
    runtime = server.runtime
    runtime._turn_lock = threading.RLock()
    cancelled = threading.Event()
    runtime._cancellation_flag = cancelled
    runtime.clear_cancel = Mock(side_effect=cancelled.clear)
    runtime.cancel = Mock(side_effect=cancelled.set)
    order = []
    original_end = KratosWebHandler.end_headers

    def end_headers(handler):
        if handler.path == "/api/chat":
            # Simulate Stop at the first possible browser cancellation boundary.
            assert runtime.clear_cancel.call_count == 1
            order.append("headers")
            runtime.cancel()
        return original_end(handler)

    def execute(*args, **kwargs):
        order.append("execute")
        assert cancelled.is_set()
        assert_owned(runtime)
        return "Stopped by you"

    monkeypatch.setattr(KratosWebHandler, "end_headers", end_headers)
    runtime.run_agent.side_effect = execute
    with call(server, "/api/chat", {"prompt": "continue"}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines()
                  if line.startswith("data: ")]
    assert order == ["headers", "execute"]
    assert events[-1]["status"] == "cancelled"
    runtime.clear_cancel.assert_called_once()


def test_stream_missing_session_releases_runtime_lock_before_reply(server):
    runtime = server.runtime
    runtime._turn_lock = threading.RLock()
    runtime.memory.load_session = Mock(return_value=False)
    runtime.activate_session = Mock()
    with pytest.raises(HTTPError) as failure:
        call(server, "/api/chat", {"prompt": "continue", "session_id": "missing"})
    assert failure.value.code == 404
    runtime.activate_session.assert_not_called()
    runtime.run_agent.assert_not_called()
    assert runtime._turn_lock.acquire(timeout=2)
    runtime._turn_lock.release()
