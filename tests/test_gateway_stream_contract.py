import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from kratos_agent.brain.config import BrainError, BrainTimeoutError
from kratos_agent.sdk.client import KratosClient


class Stream:
    status_code = 200

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_lines(self, **_):
        for event in self.events:
            yield ('data: ' + (event if isinstance(event, str) else json.dumps(event))).encode()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('KRATOS_MODEL', 'configured-combo')
    return KratosClient(provider='gateway', configured_model='configured-combo', max_retries=2)


@pytest.mark.parametrize('text_api', [False, True])
def test_partial_stream_without_terminal_event_is_failure_without_replay(client, text_api):
    client.session.post = Mock(return_value=Stream([{'choices': [{'delta': {'content': 'partial'}}]}]))
    with pytest.raises(BrainError, match='interrupted') as exc:
        if text_api:
            list(client.stream_text({'model': 'configured-combo'}))
        else:
            client.complete({'model': 'configured-combo'})
    assert exc.value.partial_text == 'partial'
    assert client.session.post.call_count == 1


def test_sse_error_is_not_silently_accepted(client):
    client.session.post = Mock(return_value=Stream([
        {'choices': [{'delta': {'content': 'partial'}}]},
        {'error': {'message': 'upstream failed'}}, '[DONE]',
    ]))
    with pytest.raises(BrainError, match='interrupted'):
        client.complete({'model': 'configured-combo'})
    assert client.session.post.call_count == 1


def test_incomplete_tool_call_never_becomes_executable(client):
    client.session.post = Mock(return_value=Stream([{'choices': [{'delta': {'tool_calls': [
        {'index': 0, 'id': 'call-1', 'function': {'name': 'delete_file', 'arguments': '{"path":"x"}'}}
    ]}}]}]))
    with pytest.raises(BrainError, match='interrupted'):
        client.complete({'model': 'configured-combo'})
    assert client.session.post.call_count == 1


def test_request_policy_scopes_memory_and_preserves_correlation(client):
    client.session.post = Mock(return_value=Stream([
        {'choices': [{'delta': {'content': 'done'}, 'finish_reason': 'stop'}]}, '[DONE]',
    ]))
    client.complete({'model': 'configured-combo'}, session_id='session-7', request_id='request-9')
    headers = client.session.post.call_args.kwargs['headers']
    assert headers['x-omniroute-no-memory'] == 'true'
    assert headers['X-Request-Id'] == 'request-9'
    assert headers['x-session-id'] == 'session-7'


def test_complete_terminal_stream_succeeds(client):
    client.session.post = Mock(return_value=Stream([
        {'choices': [{'delta': {'content': 'done'}, 'finish_reason': 'stop'}]},
    ]))
    assert client.complete({'model': 'configured-combo'}).text == 'done'


def test_gateway_scope_retains_session_and_cleans_up(client):
    from kratos_agent.sdk.client import gateway_scope
    client.session.post = Mock(return_value=Stream([
        {'choices': [{'delta': {'content': 'done'}, 'finish_reason': 'stop'}]},
    ]))
    with gateway_scope(session_id='session-1', task_id='task-1'):
        client.complete({'model': 'configured-combo'})
        headers = client.session.post.call_args.kwargs['headers']
        assert headers['x-session-id'] == 'session-1'
        assert headers['x-kratos-task-id'] == 'task-1'
    client.complete({'model': 'configured-combo'})
    assert 'x-session-id' not in client.session.post.call_args.kwargs['headers']


def test_cancelled_task_never_dispatches_request(client):
    from threading import Event

    from kratos_agent.sdk.client import gateway_scope
    cancellation = Event()
    cancellation.set()
    client.session.post = Mock()
    with gateway_scope(cancel=cancellation), pytest.raises(BrainError, match='cancelled'):
        client.complete({'model': 'configured-combo'})
    client.session.post.assert_not_called()


def test_cancel_during_stream_does_not_return_tool_calls(client):
    from threading import Event

    from kratos_agent.sdk.client import gateway_scope
    cancellation = Event()
    client.session.post = Mock(return_value=Stream([
        {'choices': [{'delta': {'content': 'first'}}]},
        {'choices': [{'delta': {}, 'finish_reason': 'stop'}]},
    ]))
    with gateway_scope(cancel=cancellation), pytest.raises(BrainError, match='cancelled'):
        client.complete({'model': 'configured-combo'}, on_chunk=lambda _: cancellation.set())
    assert client.session.post.call_count == 1


def test_cancel_interrupts_silent_upstream_after_sse_headers(monkeypatch):
    from kratos_agent.sdk.client import gateway_scope

    monkeypatch.setenv('KRATOS_MODEL', 'configured-combo')
    headers_sent = threading.Event()
    release = threading.Event()
    cancellation = threading.Event()
    errors = []

    class SilentHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.flush()
            headers_sent.set()
            release.wait(5)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), SilentHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client = KratosClient(endpoint_url=f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                          provider='gateway', configured_model='configured-combo', timeout=5, max_retries=0)

    def request():
        try:
            with gateway_scope(cancel=cancellation):
                client.complete({'model': 'configured-combo'})
        except BrainError as exc:
            errors.append(exc)

    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    try:
        assert headers_sent.wait(2)
        cancellation.set()
        worker.join(2)
        assert not worker.is_alive(), 'cancellation left a silent upstream read blocked'
        assert len(errors) == 1 and 'cancelled' in str(errors[0])
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        client.session.close()


@pytest.mark.parametrize('cancel_scope', [False, True])
def test_sse_heartbeat_cannot_extend_request_deadline(cancel_scope):
    from kratos_agent.sdk.client import gateway_scope

    headers_sent = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    errors = []

    class HeartbeatHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.wfile.flush()
            headers_sent.set()
            try:
                while not release.wait(0.03):
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), HeartbeatHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = KratosClient(endpoint_url=f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                          provider='gateway', configured_model='configured-combo', timeout=0.3, max_retries=0)

    def request():
        try:
            with gateway_scope(cancel=threading.Event() if cancel_scope else None):
                client.complete({'model': 'configured-combo'})
        except BrainError as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    try:
        assert headers_sent.wait(2)
        assert finished.wait(1.5), 'upstream heartbeats kept the request pending after its deadline'
        assert len(errors) == 1
        assert isinstance(errors[0], BrainTimeoutError)
    finally:
        release.set()
        worker.join(2)
        server.shutdown()
        server.server_close()
        client.session.close()


@pytest.mark.parametrize('text_api', [False, True])
def test_short_sse_reply_finishes_before_gateway_closes_connection(text_api):
    """A completed reply smaller than requests' buffer must leave pending state."""
    headers_sent = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    results = []
    errors = []

    class KeepOpenHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            self.wfile.flush()
            headers_sent.set()
            release.wait(5)
            self.close_connection = True

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), KeepOpenHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = KratosClient(endpoint_url=f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                          provider='gateway', configured_model='configured-combo', timeout=4, max_retries=0)

    def request():
        try:
            if text_api:
                results.append(''.join(client.stream_text({'model': 'configured-combo'})))
            else:
                results.append(client.complete({'model': 'configured-combo'}).text)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=request, daemon=True)
    worker.start()
    try:
        assert headers_sent.wait(2)
        assert finished.wait(1), 'complete SSE reply stayed buffered while the gateway connection was open'
        assert not errors
        assert results == ['OK']
    finally:
        release.set()
        worker.join(5)
        server.shutdown()
        server.server_close()
        client.session.close()
