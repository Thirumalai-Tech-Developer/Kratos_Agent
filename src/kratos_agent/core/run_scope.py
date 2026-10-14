"""Execution-local callbacks, cancellation and resource ownership."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import threading
import time
from typing import Any

current_runtime: ContextVar[Any] = ContextVar("kratos_runtime", default=None)
current_loop: ContextVar[Any] = ContextVar("kratos_loop", default=None)
current_job: ContextVar[str | None] = ContextVar("kratos_job", default=None)


@contextmanager
def runtime_scope(runtime):
    token = current_runtime.set(runtime)
    try:
        yield
    finally:
        current_runtime.reset(token)


def loop_scope(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        token = current_loop.set(self)
        try:
            return method(self, *args, **kwargs)
        finally:
            current_loop.reset(token)
    return wrapped


_locks: dict[str, threading.RLock] = {}
_lock_guard = threading.Lock()


@contextmanager
def resource_lock(resource: str, *, cancel_event=None, wait_timeout=30):
    """Serialize conflicting resources between runs in this process."""
    with _lock_guard:
        lock = _locks.setdefault(resource, threading.RLock())
    deadline = time.monotonic() + wait_timeout
    while not lock.acquire(timeout=0.1):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Cancelled while waiting for resource")
        if time.monotonic() >= deadline:
            raise TimeoutError("Resource is busy: " + resource)
    try:
        yield
    finally:
        lock.release()
