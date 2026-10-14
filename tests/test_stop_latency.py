import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kratos_agent.brain.config import BrainError
from kratos_agent.sdk.client import KratosClient, gateway_scope


@pytest.mark.parametrize("phase", ["headers", "json-body"])
def test_stop_interrupts_request_before_response_completes(monkeypatch, phase):
    monkeypatch.setenv("KRATOS_MODEL_PROVIDER", "gateway")
    monkeypatch.setenv("KRATOS_MODEL", "test-model")
    reached = threading.Event()
    release = threading.Event()
    cancel = threading.Event()
    errors = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if phase == "json-body":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.flush()
            reached.set()
            release.wait(10)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = KratosClient(endpoint_url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                          timeout=30, max_retries=2)

    def run():
        try:
            with gateway_scope(cancel=cancel):
                client.complete({"model": "test-model"}, stream=phase != "json-body")
        except Exception as exc:  # noqa: BLE001 -- Capture worker failures for the main test thread.
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert reached.wait(2)
        started = time.monotonic()
        cancel.set()
        worker.join(1.5)
        elapsed = time.monotonic() - started
        assert not worker.is_alive(), f"Stop still blocked in {phase} after {elapsed:.2f}s"
        assert len(errors) == 1 and isinstance(errors[0], BrainError)
        assert "cancelled" in str(errors[0])
        print(f"{phase} stopped in {elapsed:.3f}s")
    finally:
        release.set()
        worker.join(2)
        server.shutdown()
        server.server_close()
        client.session.close()


def test_stop_waits_for_async_tool_cleanup_before_returning():
    from kratos_agent.core.execution_control import execution_scope
    from kratos_agent.utils.async_runner import run_coroutine

    started = threading.Event()
    cleaned = threading.Event()
    cancel = threading.Event()
    errors = []

    async def operation():
        started.set()
        try:
            await asyncio.sleep(300)
        finally:
            await asyncio.sleep(0.05)
            cleaned.set()

    def run():
        try:
            with execution_scope(cancel):
                run_coroutine(operation())
        except Exception as exc:  # noqa: BLE001 -- Capture worker failures for the main test thread.
            errors.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert started.wait(2)
    cancel.set()
    worker.join(1.5)
    assert not worker.is_alive(), "Stop left the async tool running"
    assert cleaned.is_set(), "Runtime returned before tool cleanup completed"
    assert len(errors) == 1 and isinstance(errors[0], InterruptedError)
