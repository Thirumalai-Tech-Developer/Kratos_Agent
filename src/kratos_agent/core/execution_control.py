"""Cancellation scoped to the current tool worker and its own child process tree."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import subprocess
import threading
import time

import psutil

_cancel: ContextVar[threading.Event | None] = ContextVar("kratos_tool_cancel", default=None)


@contextmanager
def execution_scope(cancel: threading.Event):
    token = _cancel.set(cancel)
    try:
        yield
    finally:
        _cancel.reset(token)


def current_cancel_event() -> threading.Event | None:
    return _cancel.get()


def stop_process_tree(process: subprocess.Popen) -> None:
    """Stop only descendants of the command owned by this worker."""
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.Error:
                pass
        try:
            parent.kill()
        except psutil.Error:
            pass
        psutil.wait_procs(children, timeout=1)
    except psutil.Error:
        if process.poll() is None:
            process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def collect_command_output(process: subprocess.Popen, timeout: float = 300) -> str:
    """communicate's bounded wait checks Stop even when a command prints nothing."""
    deadline = time.monotonic() + timeout
    cancellation = current_cancel_event()
    def stop_and_drain() -> None:
        stop_process_tree(process)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    while True:
        if cancellation is not None and cancellation.is_set():
            stop_and_drain()
            raise InterruptedError("Command cancelled by user")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop_and_drain()
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            output, _ = process.communicate(timeout=min(0.1, remaining))
            return output or ""
        except subprocess.TimeoutExpired:
            continue
