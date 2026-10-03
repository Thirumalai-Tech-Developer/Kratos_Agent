import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

import pytest

from kratos_agent.web.server import KratosServer, KratosWebHandler


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv('KRATOS_INTERNAL_TOKEN', 'private-test-token')
    runtime = SimpleNamespace(
        run_agent=Mock(return_value='verified result'), cancel=Mock(), model_name='model',
        memory=SimpleNamespace(active_session=SimpleNamespace(session_id='test-session')),
    )
    instance = KratosServer(('127.0.0.1', 0), KratosWebHandler, Mock(), Mock(), runtime)
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    worker.join()


def call(server, path, payload=None, token='private-test-token'):
    request = Request(f'http://127.0.0.1:{server.server_port}{path}',
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Content-Type': 'application/json', 'X-Kratos-Internal-Token': token})
    return build_opener(ProxyHandler({})).open(request, timeout=5)


def test_internal_api_rejects_missing_token(server):
    with pytest.raises(HTTPError) as exc:
        call(server, '/api/health', token='')
    assert exc.value.code == 401
    assert json.load(call(server, '/api/health'))['service'] == 'kratos'


def test_voice_command_executes_real_runtime(server):
    result = json.load(call(server, '/api/voice/command', {'command': 'inspect workspace'}))
    server.runtime.run_agent.assert_called_once_with('inspect workspace', agent_mode=True)
    assert result['result'] == 'verified result'


def test_voice_stream_emits_result_and_terminal_event(server):
    with call(server, '/api/voice/stream', {'transcript': 'inspect workspace'}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
    assert any(event.get('type') == 'done' and event.get('result') == 'verified result' for event in events)
    server.runtime.run_agent.assert_called_once()


def test_second_turn_cannot_switch_running_session(server):
    server.turn_lock.acquire()
    try:
        with pytest.raises(HTTPError) as exc:
            call(server, '/api/chat/sync', {'prompt': 'other task', 'session_id': 'other'})
        assert exc.value.code == 409
        server.runtime.run_agent.assert_not_called()
    finally:
        server.turn_lock.release()


def test_cancel_reaches_runtime(server):
    assert json.load(call(server, '/api/chat/cancel', {}))['status'] == 'cancellation_requested'
    server.runtime.cancel.assert_called_once()


@pytest.mark.parametrize('path,payload,method', [
    ('/api/sessions/other', None, 'GET'),
    ('/api/sessions', {'title': 'Other'}, 'POST'),
    ('/api/sessions/other', None, 'DELETE'),
])
def test_session_changes_rejected_during_turn(server, path, payload, method):
    server.turn_lock.acquire()
    try:
        request = Request(f'http://127.0.0.1:{server.server_port}{path}',
                          method=method,
                          data=json.dumps(payload).encode() if payload else None,
                          headers={'X-Kratos-Internal-Token': 'private-test-token'})
        with pytest.raises(HTTPError) as exc:
            build_opener(ProxyHandler({})).open(request, timeout=5)
        assert exc.value.code == 409
    finally:
        server.turn_lock.release()


@pytest.mark.parametrize('result,expected', [
    ('Model request failed: interrupted', 'failed'),
    ('Execution error: disconnected', 'failed'),
    ('Stopped after 10 steps', 'failed'),
])
def test_failed_runtime_result_never_reports_success(server, result, expected):
    server.runtime.run_agent.return_value = result
    with call(server, '/api/voice/stream', {'command': 'run task'}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
    assert next(e for e in events if e['type'] == 'done')['status'] == expected
    assert not any(e.get('step', {}).get('tag') == 'COMPLETE' for e in events)


def test_cancelled_turn_has_cancelled_terminal_state(server):
    server.runtime._cancellation_flag = threading.Event()
    server.runtime._cancellation_flag.set()
    result = json.load(call(server, '/api/voice/command', {'command': 'task'}))
    assert result['status'] == 'cancelled'


def test_server_uses_runtime_memory_owner(server):
    assert server.memory is server.runtime.memory


def test_tool_events_keep_call_ids_failure_and_result_separate_from_model_reply(server):
    from kratos_agent.core.event_bus import event_bus
    from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

    def execute(*args, **kwargs):
        event_bus.publish(RuntimeEvent(EventKind.TOOL_CALL_STARTED, {"name": "read_file", "call_id": "call-1", "arguments": {"file_path": "missing.py"}}))
        event_bus.publish(RuntimeEvent(EventKind.TOOL_FAILED, {"name": "read_file", "call_id": "call-1", "content": "File missing", "is_error": True}))
        return "Could not find the requested file."

    server.runtime.run_agent.side_effect = execute
    with call(server, '/api/voice/stream', {'command': 'read missing file'}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
    started = next(event for event in events if event['type'] == 'tool_call')
    failed = next(event for event in events if event['type'] == 'tool_failed')
    assert started['tool_call']['call_id'] == failed['call_id'] == 'call-1'
    assert failed['is_error'] and failed['status'] == 'failed'
    assert failed['result'] == 'File missing'
    assert next(event for event in events if event['type'] == 'done')['result'] == 'Could not find the requested file.'
