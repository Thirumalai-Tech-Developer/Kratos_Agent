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


def test_stream_reports_preparation_and_actual_model_request(server):
    from kratos_agent.core.event_bus import event_bus
    from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

    def run(*args, **kwargs):
        event_bus.publish(RuntimeEvent(EventKind.REQUEST_ASSEMBLED, {}))
        return 'Hello!'

    server.runtime.run_agent.side_effect = run
    with call(server, '/api/chat', {'prompt': 'hii'}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
    tags = [ev['step']['tag'] for ev in events if ev.get('type') == 'step']
    assert tags == ['PREPARING', 'MODEL', 'COMPLETED']
    assert events[-1]['status'] == 'completed'


def test_second_turn_cannot_switch_running_session(server):
    server.turn_lock.acquire()
    try:
        with pytest.raises(HTTPError) as exc:
            call(server, '/api/chat/sync', {'prompt': 'other task', 'session_id': 'other'})
        assert exc.value.code == 409
        server.runtime.run_agent.assert_not_called()
    finally:
        server.turn_lock.release()


def test_recoverable_tool_format_retry_stays_active_and_does_not_emit_failure(server):
    from kratos_agent.core.event_bus import event_bus
    from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

    release = threading.Event()

    def run(*args, **kwargs):
        event_bus.publish(RuntimeEvent(EventKind.RETRY, {
            'reason': 'tool_call_format', 'error': 'tool_call_format', 'recoverable': True,
            'attempt': 4, 'strategy': 'single_json', 'label': 'Trying a different format',
        }))
        assert release.wait(4)
        return 'Verified architecture report'

    server.runtime.run_agent.side_effect = run
    try:
        with call(server, '/api/chat', {'prompt': 'inspect architecture'}) as response:
            events = []
            for raw in response:
                if not raw.startswith(b'data: '):
                    continue
                events.append(json.loads(raw[6:]))
                if events[-1].get('type') == 'retry':
                    break
            retry = events[-1]
            assert retry['type'] == 'retry'
            assert retry['recoverable'] is True and retry['attempt'] == 4
            assert retry['reason'] == 'tool_call_format' and retry['strategy'] == 'single_json'
            assert not any(event['type'] in ('error', 'done') for event in events)
            assert server.turn_lock.locked()
            assert json.load(call(server, '/api/health'))['busy'] is True
            release.set()
            events.extend(json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: '))
        assert not any(event['type'] == 'error' for event in events)
        assert not any(event.get('step', {}).get('tag') == 'REPAIRING' for event in events)
        assert events[-1]['type'] == 'done' and events[-1]['status'] == 'completed'
        assert events[-1]['result'] == 'Verified architecture report'
    finally:
        release.set()


def test_cancel_reaches_runtime(server):
    assert json.load(call(server, '/api/chat/cancel', {}))['status'] == 'cancellation_requested'
    server.runtime.cancel.assert_called_once()


def test_model_catalog_refresh_reaches_gateway_and_keeps_cold_start_budget(server, monkeypatch):
    from kratos_agent.brain import config
    catalog = Mock(return_value=[{'id': 'model', 'is_configured': True}])
    monkeypatch.setattr(config, 'get_runtime_model_catalog', catalog)
    monkeypatch.setattr(config, 'get_model_provider', lambda: 'gateway')
    assert json.load(call(server, '/api/models?refresh=1'))['models'][0]['id'] == 'model'
    assert catalog.call_args.kwargs['refresh'] is True
    assert catalog.call_args.kwargs['timeout'] == 15.0


def test_connection_diagnostics_do_not_expose_session_secrets(server, tmp_path, monkeypatch):
    from kratos_agent.brain.account_store import AccountStore
    from kratos_agent.brain.chatgpt_web import ChatGPTWebAccounts
    manager = ChatGPTWebAccounts(AccountStore(tmp_path))
    state = manager.store.read()
    state['web_accounts'] = {'one': {'storage_state': {'cookies': [{'value': 'private-cookie'}]}, 'model': 'chatgpt-web/test'}}
    manager.store.write(state)
    monkeypatch.setattr('kratos_agent.brain.chatgpt_web.chatgpt_web_accounts', manager)
    result = json.load(call(server, '/api/browser/status'))
    assert result['panel_ready'] is False and result['connected_accounts'] == 1
    assert 'private-cookie' not in json.dumps(result)


def test_context_endpoint_returns_counts_without_raw_prompt(server):
    server.runtime.context_status = Mock(return_value={'used_tokens': 1234, 'input_limit': 248000})
    assert json.load(call(server, '/api/context')) == {'used_tokens': 1234, 'input_limit': 248000}
    server.runtime.context_status.assert_called_with(busy=False)


def test_manual_context_compaction_returns_updated_usage(server):
    server.runtime.compact_context = Mock(return_value={'compacted': True, 'context': {'used_tokens': 1200}})
    result = json.load(call(server, '/api/context/compact', {'session_id': 'test-session'}))
    assert result['compacted'] and result['context']['used_tokens'] == 1200
    server.runtime.compact_context.assert_called_once()


@pytest.mark.parametrize('busy_lock', ['http', 'runtime'])
def test_context_compaction_cannot_interrupt_an_active_task(server, busy_lock):
    server.runtime.compact_context = Mock()
    server.runtime._turn_lock = threading.Lock()
    lock = server.turn_lock if busy_lock == 'http' else server.runtime._turn_lock
    lock.acquire()
    try:
        with pytest.raises(HTTPError) as exc:
            call(server, '/api/context/compact', {})
        assert exc.value.code == 409
        server.runtime.compact_context.assert_not_called()
    finally:
        lock.release()


def test_context_compaction_rejects_a_stale_session(server):
    server.runtime.compact_context = Mock()
    with pytest.raises(HTTPError) as exc:
        call(server, '/api/context/compact', {'session_id': 'other-session'})
    assert exc.value.code == 409
    server.runtime.compact_context.assert_not_called()


def test_stream_updates_context_on_request_response_and_compaction(server):
    from kratos_agent.core.event_bus import event_bus
    from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

    server.runtime.context_status = Mock(return_value={'used_tokens': 1234, 'input_limit': 248000})
    def run(*args, **kwargs):
        for kind in (EventKind.COMPACTED, EventKind.REQUEST_ASSEMBLED, EventKind.MODEL_RESPONSE):
            event_bus.publish(RuntimeEvent(kind, {}))
        return 'Hello!'
    server.runtime.run_agent.side_effect = run
    with call(server, '/api/chat', {'prompt': 'hi'}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
    assert len([event for event in events if event['type'] == 'context']) == 3


def test_users_run_simultaneously_and_stop_only_their_own_worker(server, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    starts = [threading.Event(), threading.Event()]
    releases = [threading.Event(), threading.Event()]
    children = []
    workers = {}
    for index, profile in enumerate(['a' * 32, 'b' * 32]):
        def run(*args, i=index, **kwargs):
            starts[i].set()
            assert releases[i].wait(5)
            return f'user-{i}-reply'
        runtime = SimpleNamespace(run_agent=Mock(side_effect=run), cancel=Mock(side_effect=releases[index].set), model_name=f'model-{index}',
                                  workspace=tmp_path / profile, memory=SimpleNamespace(active_session=SimpleNamespace(session_id=f'session-{index}')))
        child = KratosServer(('127.0.0.1', 0), KratosWebHandler, Mock(), Mock(), runtime)
        threading.Thread(target=child.serve_forever, daemon=True).start()
        children.append(child)
        workers[profile] = SimpleNamespace(port=child.server_port, token='private-test-token')
    server.user_workers = SimpleNamespace(route=lambda profile: workers[profile], is_ready=lambda worker: True, close=Mock())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(lambda p=profile: json.load(call(server, f'/api/chat/sync?profile={p}', {'prompt': 'work'}))) for profile in workers]
            assert starts[0].wait(3) and starts[1].wait(3)
            assert all(child.turn_lock.locked() for child in children)
            json.load(call(server, f'/api/chat/cancel?profile={"a" * 32}', {}))
            assert releases[0].is_set() and not releases[1].is_set()
            assert children[1].turn_lock.locked()
            releases[1].set()
            assert futures[0].result()['result'] == 'user-0-reply'
            assert futures[1].result()['result'] == 'user-1-reply'
            children[0].runtime.cancel.assert_called_once()
            children[1].runtime.cancel.assert_not_called()
    finally:
        for release in releases:
            release.set()
        for child in children:
            child.shutdown()
            child.server_close()


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


@pytest.mark.parametrize('method', ['GET', 'DELETE'])
def test_session_switch_and_delete_reject_direct_runtime_turn_without_touching_old_session(server, method):
    old = SimpleNamespace(session_id='old-active-session')
    server.memory.active_session = old
    server.runtime.memory = server.memory
    server.memory.load_session = Mock(return_value=True)
    server.memory.delete_session = Mock(return_value=True)
    server.runtime.activate_session = Mock()
    server.runtime._turn_lock = threading.RLock()
    server.runtime._turn_lock.acquire()
    try:
        request = Request(f'http://127.0.0.1:{server.server_port}/api/sessions/other', method=method,
                          headers={'X-Kratos-Internal-Token': 'private-test-token'})
        with pytest.raises(HTTPError) as exc:
            build_opener(ProxyHandler({})).open(request, timeout=5)
        assert exc.value.code == 409
        assert server.memory.active_session is old
        server.memory.load_session.assert_not_called()
        server.memory.delete_session.assert_not_called()
        server.runtime.activate_session.assert_not_called()
        # The HTTP error headers may arrive just before the handler's finally
        # releases its lock; require prompt release rather than racing it.
        assert server.turn_lock.acquire(timeout=1)
        server.turn_lock.release()
    finally:
        server.runtime._turn_lock.release()


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


def test_scoped_subagent_activity_never_becomes_parent_reply_or_task_step(server):
    from kratos_agent.core.event_bus import event_bus
    from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent

    scope = {"agent_id": "child-one", "role": "reviewer", "task": "Inspect source", "status": "running"}
    def run(*args, **kwargs):
        event_bus.publish(RuntimeEvent(EventKind.SUBAGENT_STARTED, {"subagent":scope}))
        event_bus.publish(RuntimeEvent(EventKind.MODEL_CHUNK,
            {"subagent":scope, "chunk":"CHILD_PRIVATE_MODEL_TEXT"}))
        event_bus.publish(RuntimeEvent(EventKind.SUBAGENT_UPDATED, {
            "subagent":scope, "activity":{"kind":"tool.started",
                "payload":{"name":"read_file","arguments":{"file_path":"app.py"}}}}))
        event_bus.publish(RuntimeEvent(EventKind.SUBAGENT_COMPLETED, {
            "subagent":{**scope,"status":"completed"}, "result":"Verified child report", "duration_ms":15}))
        event_bus.publish(RuntimeEvent(EventKind.MODEL_CHUNK, {"chunk":"PARENT_FINAL_REPLY"}))
        return "PARENT_FINAL_REPLY"
    server.runtime.run_agent.side_effect = run
    with call(server, "/api/chat", {"prompt":"Review the project"}) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith("data: ")]
    activity = [event["event"] for event in events if event.get("type") == "runtime_event"]
    assert [event["kind"] for event in activity if event["kind"].startswith("subagent.")] == [
        "subagent.started", "subagent.updated", "subagent.completed"]
    assert all(event["payload"]["subagent"]["agent_id"] == "child-one" for event in activity)
    assert "CHILD_PRIVATE_MODEL_TEXT" not in json.dumps(events)
    assert any(event.get("token") == "PARENT_FINAL_REPLY" for event in events)
    assert not any(event.get("type") == "step" and event.get("step", {}).get("tag") == "TOOL CALL"
                   for event in events)
    assert events[-1]["status"] == "completed"


def test_new_chat_api_creates_current_model_session_without_clearing_old_data(server):
    fresh = SimpleNamespace(session_id="fresh-chat",title="New Session",model="model",
                            created_at="now",updated_at="now")
    server.memory.create_session = Mock(return_value=fresh)
    server.memory.clear = Mock()
    server.runtime.activate_session = Mock()
    result = json.load(call(server, "/api/sessions", {}))
    assert result["session_id"] == "fresh-chat" and result["model"] == "model"
    server.memory.create_session.assert_called_once_with(title="New Session", model="model")
    server.memory.clear.assert_not_called()
    server.runtime.activate_session.assert_called_once()


def test_new_chat_api_rejects_cli_turn_and_unknown_model(server):
    server.memory.create_session = Mock()
    server.runtime._turn_lock = threading.RLock()
    server.runtime._turn_lock.acquire()
    try:
        with pytest.raises(HTTPError) as exc:
            call(server, "/api/sessions", {})
        assert exc.value.code == 409
        server.memory.create_session.assert_not_called()
    finally:
        server.runtime._turn_lock.release()
    with pytest.raises(HTTPError) as exc:
        call(server, "/api/sessions", {"model":"unselected-model"})
    assert exc.value.code == 400
    server.memory.create_session.assert_not_called()
