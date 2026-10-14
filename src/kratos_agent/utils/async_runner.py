import asyncio
import threading
from collections.abc import Coroutine
from typing import Any

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
    from kratos_agent.core.execution_control import current_cancel_event

    cancellation = current_cancel_event()

    async def scoped():
        task = asyncio.create_task(coro)

        async def watch():
            while not cancellation.is_set():
                await asyncio.sleep(0.05)
            task.cancel()

        watcher = asyncio.create_task(watch()) if cancellation is not None else None
        try:
            if cancellation is not None and cancellation.is_set():
                task.cancel()
            return await task
        except asyncio.CancelledError:
            raise InterruptedError("Operation cancelled by user") from None
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            # Await the task's finally blocks before releasing the runtime turn.
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    loop = get_shared_event_loop()
    future = asyncio.run_coroutine_threadsafe(scoped(), loop)
    return future.result(timeout=timeout)
