"""Foreground CLI exit may overlap background event-loop closure."""
from unittest.mock import MagicMock, patch

from kratos_agent.live.runtime import LiveRuntime


def test_loop_closing_while_stop_is_scheduled_does_not_break_exit():
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._thread = None
    runtime._loop = MagicMock()
    runtime._loop.is_closed.side_effect = [False, True, True]
    runtime._loop.is_running.return_value = True
    runtime._loop.call_soon_threadsafe.side_effect = RuntimeError("Event loop is closed")
    coroutine = MagicMock()
    runtime.stop = MagicMock(return_value=coroutine)
    with patch("kratos_agent.live.runtime.asyncio.run_coroutine_threadsafe", side_effect=RuntimeError("Event loop is closed")):
        runtime.stop_background()
    coroutine.close.assert_called_once()


def test_already_closed_loop_can_be_stopped_repeatedly():
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._thread = None
    runtime._loop = MagicMock()
    runtime._loop.is_closed.return_value = True
    runtime.stop = MagicMock()
    runtime.stop_background()
    runtime.stop_background()
    runtime.stop.assert_not_called()
