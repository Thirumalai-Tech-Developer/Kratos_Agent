import asyncio
import threading
from typing import Any, Coroutine

_SHARED_LOOP: asyncio.AbstractEventLoop | None = None
_SHARED_THREAD: threading.Thread | None = None
_LOOP_LOCK = threading.Lock()


def get_shared_event_loop() -> asyncio.AbstractEventLoop:
    """Returns a running shared background event loop, starting it on a daemon thread if needed."""
    global _SHARED_LOOP, _SHARED_THREAD
    with _LOOP_LOCK:
        if _SHARED_LOOP is None or _SHARED_LOOP.is_closed() or not _SHARED_LOOP.is_running():
            _SHARED_LOOP = asyncio.new_event_loop()
            ready_evt = threading.Event()

            def _thread_target():
                asyncio.set_event_loop(_SHARED_LOOP)
                _SHARED_LOOP.call_soon(ready_evt.set)
                _SHARED_LOOP.run_forever()

            _SHARED_THREAD = threading.Thread(
                target=_thread_target,
                daemon=True,
                name="kratos-shared-loop-worker",
            )
            _SHARED_THREAD.start()
            ready_evt.wait(timeout=2.0)
        return _SHARED_LOOP


def run_coroutine(coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
    """Safely executes an async coroutine from synchronous threads via the shared background loop."""
    loop = get_shared_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
