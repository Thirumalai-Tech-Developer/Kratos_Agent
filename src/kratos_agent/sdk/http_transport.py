"""Interrupt the sockets owned by a model request, including before headers arrive."""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from http.client import HTTPResponse

from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ReadTimeoutError

_request: ContextVar[object | None] = ContextVar("kratos_http_request", default=None)


class _Request:
    def __init__(self, cancel, timeout):
        self.cancel = cancel
        # requests normally applies this as an idle read timeout. Keep a
        # separate deadline so SSE heartbeats cannot extend an attempt forever.
        read_timeout = timeout[1] if isinstance(timeout, tuple) else timeout
        self.deadline = (
            time.monotonic() + float(read_timeout)
            if isinstance(read_timeout, (int, float)) and math.isfinite(read_timeout) and read_timeout > 0
            else None
        )


class _Response(HTTPResponse):
    def __init__(self, sock, *args, **kwargs):
        super().__init__(sock, *args, **kwargs)
        request = _request.get()
        if request is None:
            return
        raw = self.fp.raw

        def readinto(buffer):
            timeout = sock.gettimeout()
            deadline = time.monotonic() + timeout if timeout is not None else None
            try:
                while True:
                    if request.cancel is not None and request.cancel.is_set():
                        raise InterruptedError("Model request cancelled")
                    remaining = deadline - time.monotonic() if deadline is not None else 0.1
                    if request.deadline is not None:
                        remaining = min(remaining, request.deadline - time.monotonic())
                    if remaining <= 0:
                        raise TimeoutError("Model response timed out")
                    sock.settimeout(min(0.1, remaining))
                    try:
                        return sock.recv_into(buffer)
                    except TimeoutError:
                        continue
            finally:
                sock.settimeout(timeout)

        # Interrupt in the reading thread. Closing a Windows socket from another
        # thread need not wake its pending select(), and can block on reader locks.
        raw.readinto = readinto


class _TrackedConnection:
    response_class = _Response

    def request(self, *args, **kwargs):
        request = _request.get()
        if request is not None and request.cancel is not None and request.cancel.is_set():
            raise InterruptedError("Model request cancelled")
        return super().request(*args, **kwargs)


class _HTTPConnection(_TrackedConnection, HTTPConnection):
    pass


class _HTTPSConnection(_TrackedConnection, HTTPSConnection):
    pass


class _HTTPPool(HTTPConnectionPool):
    ConnectionCls = _HTTPConnection


class _HTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _HTTPSConnection


class CancellableHTTPAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        # Keep urllib3's global pool registry unchanged for unrelated clients.
        self.poolmanager.pool_classes_by_scheme = {"http": _HTTPPool, "https": _HTTPSPool}


@contextmanager
def cancellable_post(session, cancel, *args, **kwargs):
    """Keep the cancellation watcher alive until the response body is consumed."""
    request = _Request(cancel, kwargs.get("timeout"))
    token = _request.set(request)
    response = None
    try:
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Model request cancelled")
        response = session.post(*args, **kwargs)
        yield response
    except RequestsConnectionError as exc:
        # requests wraps streamed urllib3 read timeouts as ConnectionError.
        # Preserve their timeout classification without exposing upstream text.
        if exc.args and isinstance(exc.args[0], ReadTimeoutError):
            raise RequestsTimeout("Model response timed out") from exc
        raise
    finally:
        _request.reset(token)
        if response is not None:
            close = getattr(response, "close", None)
            if close is not None:
                close()
