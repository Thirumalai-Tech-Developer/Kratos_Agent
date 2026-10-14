"""Private, reusable JSONL workers for an account's owned browser executor."""

from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import threading
import time
import uuid
import weakref

from .config import BrainError, BrainTimeoutError


MAX_FRAME_BYTES = 12 * 1024 * 1024
_pools: weakref.WeakSet = weakref.WeakSet()
_pools_lock = threading.Lock()


def _close_all_pools():
    with _pools_lock:
        pools = list(_pools)
    for pool in pools:
        pool.close()


atexit.register(_close_all_pools)


def _finalize_workers(workers, lock, stop):
    stop.set()
    with lock:
        remaining = list(workers.values())
        workers.clear()
    for worker in remaining:
        worker.close()


class _Worker:
    def __init__(self, command, *, cwd, env):
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.closed = False
        self.leases = 0  # Accessed only while the owning pool's lock is held.
        self.last_used = time.monotonic()
        self.responses = queue.Queue()
        self.descendants = {}
        self._capture_descendants()
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._discard_errors, daemon=True).start()

    def _read_output(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(MAX_FRAME_BYTES + 1)
                if not line:
                    self.responses.put(None)
                    return
                if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
                    self.responses.put(False)
                    return
                # A worker has exactly one outstanding request. Unexpected extra
                # output invalidates it instead of becoming the next turn's reply.
                if not self.responses.empty():
                    self.responses.put(False)
                    return
                self.responses.put(line)
        except (OSError, ValueError):
            self.responses.put(None)

    def _discard_errors(self):
        # Dependency diagnostics may include request data. Drain without retaining
        # or logging them; only fixed public errors reach the user.
        try:
            while self.process.stderr.read(65536):
                pass
        except (OSError, ValueError):
            pass

    def _capture_descendants(self):
        import psutil

        if self.process.poll() is not None:
            return
        try:
            for child in psutil.Process(self.process.pid).children(recursive=True):
                self.descendants[(child.pid, child.create_time())] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def close(self):
        import psutil

        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            self._capture_descendants()
            owned = list(self.descendants.values())
            if self.process.poll() is None:
                try:
                    owned.append(psutil.Process(self.process.pid))
                except psutil.NoSuchProcess:
                    pass
            for process in reversed(owned):
                try:
                    process.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            _, alive = psutil.wait_procs(owned, timeout=0.3)
            for process in alive:
                try:
                    process.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if self.process.poll() is None:
                self.process.kill()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            for stream in (
                self.process.stdin,
                self.process.stdout,
                self.process.stderr,
            ):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

    def request(self, request, *, deadline, cancel):
        while not self.lock.acquire(timeout=0.05):
            self._check(deadline, cancel)
        try:
            self._check(deadline, cancel)
            if (
                self.closed
                or self.process.poll() is not None
                or not self.responses.empty()
            ):
                raise BrainError("ChatGPT browser executor returned an invalid result")
            request_id = uuid.uuid4().hex
            data = (
                json.dumps(
                    {"request_id": request_id, "request": request}, ensure_ascii=False
                ).encode()
                + b"\n"
            )
            if len(data) > MAX_FRAME_BYTES:
                raise BrainError(
                    "ChatGPT browser request exceeds the executor's private frame limit"
                )
            write_errors = queue.Queue()

            def write():
                try:
                    self.process.stdin.write(data)
                    self.process.stdin.flush()
                except (OSError, ValueError):
                    write_errors.put(True)

            # Pipe writes can block while a child initializes. The caller keeps
            # checking Stop/deadlines and owns termination of this worker only.
            threading.Thread(target=write, daemon=True).start()
            next_capture = time.monotonic()
            while True:
                self._check(deadline, cancel)
                if not write_errors.empty():
                    raise BrainError(
                        "ChatGPT browser executor failed to receive the request"
                    )
                now = time.monotonic()
                if now >= next_capture:
                    self._capture_descendants()
                    next_capture = now + 0.2
                try:
                    line = self.responses.get(
                        timeout=min(0.05, max(0.001, deadline - now))
                    )
                except queue.Empty:
                    continue
                if line is None:
                    raise BrainError(
                        "ChatGPT browser executor stopped before returning a result"
                    )
                try:
                    frame = json.loads(line) if line is not False else None
                    if (
                        not isinstance(frame, dict)
                        or set(frame) != {"request_id", "result"}
                        or frame["request_id"] != request_id
                        or not isinstance(frame["result"], dict)
                        or not self.responses.empty()
                    ):
                        raise ValueError("Invalid private response frame")
                except (ValueError, UnicodeDecodeError) as exc:
                    raise BrainError(
                        "ChatGPT browser bridge returned an invalid result"
                    ) from exc
                self.last_used = time.monotonic()
                return json.dumps(frame["result"], ensure_ascii=False).encode()
        except BaseException:
            self.close()
            raise
        finally:
            self.lock.release()

    @staticmethod
    def _check(deadline, cancel):
        if cancel is not None and cancel.is_set():
            raise BrainError("ChatGPT browser request cancelled")
        if time.monotonic() >= deadline:
            raise BrainTimeoutError(
                "ChatGPT browser timed out; collect fresh cookies or check the local executor"
            )


class BrowserExecutorWorkers:
    """Bounded workers scoped to protected account IDs and executor source paths."""

    def __init__(self, *, max_workers=4, idle_timeout=600, cleanup_interval=30):
        self.max_workers = max(1, max_workers)
        self.idle_timeout = max(0.01, idle_timeout)
        self.cleanup_interval = max(0.01, cleanup_interval)
        self.workers = {}
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.reaper = None
        weakref.finalize(self, _finalize_workers, self.workers, self.lock, self.closed)
        with _pools_lock:
            _pools.add(self)

    def request(
        self, account_id, source, request, *, command, cwd, env, timeout, cancel=None
    ):
        deadline = time.monotonic() + timeout
        _Worker._check(deadline, cancel)
        key = (str(account_id), str(source.resolve()))
        with self.lock:
            if self.closed.is_set():
                raise BrainError("ChatGPT browser executor manager is closed")
            self._cleanup_locked()
            worker = self.workers.get(key)
            if worker is None:
                if len(self.workers) >= self.max_workers:
                    idle = [
                        (key, item)
                        for key, item in self.workers.items()
                        if not item.leases
                    ]
                    if not idle:
                        raise BrainError(
                            "ChatGPT browser executor capacity is busy; retry after an active request finishes"
                        )
                    oldest_key, oldest = min(idle, key=lambda pair: pair[1].last_used)
                    self.workers.pop(oldest_key)
                    oldest.close()
                try:
                    worker = _Worker(command, cwd=cwd, env=env)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise BrainError(
                        "ChatGPT browser executor failed to start; check Node dependencies and the executor path"
                    ) from exc
                self.workers[key] = worker
            worker.leases += 1
            if self.reaper is None:
                self.reaper = threading.Thread(
                    target=self._reap,
                    args=(weakref.ref(self), self.closed, self.cleanup_interval),
                    daemon=True,
                )
                self.reaper.start()
        try:
            return worker.request(request, deadline=deadline, cancel=cancel)
        finally:
            with self.lock:
                worker.leases -= 1
                if worker.closed and self.workers.get(key) is worker:
                    self.workers.pop(key)

    @staticmethod
    def _reap(reference, stop, interval):
        while not stop.wait(interval):
            owner = reference()
            if owner is None:
                return
            with owner.lock:
                owner._cleanup_locked()
            del owner

    def _cleanup_locked(self):
        now = time.monotonic()
        for key, worker in list(self.workers.items()):
            if not worker.leases and (
                worker.closed
                or worker.process.poll() is not None
                or now - worker.last_used >= self.idle_timeout
            ):
                self.workers.pop(key)
                worker.close()

    def close(self, account_id=None):
        with self.lock:
            if account_id is None:
                self.closed.set()
            workers = [
                self.workers.pop(key)
                for key in list(self.workers)
                if account_id is None or key[0] == str(account_id)
            ]
        for worker in workers:
            worker.close()
