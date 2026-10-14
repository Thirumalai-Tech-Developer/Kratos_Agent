"""Profile startup and reconnect contracts without devices or external requests."""
import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.events import LiveStatusHub
from kratos_agent.live.runtime import LiveRuntime
from kratos_agent.live.session import LiveSession
from kratos_agent.live.vision import VisionManager


def make_session():
    return LiveSession(
        config=LiveConfig(api_key="private-test-credential"),
        out_queue=asyncio.Queue(),
        audio_manager=SimpleNamespace(audio_in_queue=asyncio.Queue()),
        status_hub=LiveStatusHub(),
    )


def make_runtime(monkeypatch, *, backend="native"):
    def make_audio(**kwargs):
        queue = kwargs["out_queue"]
        inbound = asyncio.Queue()
        return SimpleNamespace(
            out_queue=queue, audio_in_queue=inbound,
            mic=SimpleNamespace(out_queue=queue),
            speaker=SimpleNamespace(audio_in_queue=inbound),
            start_output_only=AsyncMock(), stop=AsyncMock(),
        )

    monkeypatch.setattr("kratos_agent.live.runtime.AudioManager", make_audio)
    return LiveRuntime(LiveConfig(api_key="test-credential", backend=backend, video_mode="none"))


def test_control_only_start_and_restart_rebind_used_queues(monkeypatch):
    live = make_runtime(monkeypatch)
    hearing = Mock(side_effect=AssertionError("control startup opened hearing"))
    monkeypatch.setattr("kratos_agent.live.native_listener.get_native_hearing", hearing)
    client = Mock(side_effect=AssertionError("control startup opened Gemini"))
    monkeypatch.setattr("kratos_agent.live.session.genai.Client", client)

    async def bind_queues():
        tasks = [asyncio.create_task(queue.get()) for queue in (live.out_queue, live.audio.audio_in_queue)]
        await asyncio.sleep(0)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    try:
        status = live.ensure_control_loop(timeout=2)
        assert status["runtime_started"] and not status["speech_started"]
        asyncio.run_coroutine_threadsafe(bind_queues(), live._loop).result(timeout=2)
        old_queue, old_audio, old_lock = live.out_queue, live.audio.audio_in_queue, live.session._send_lock
        assert old_queue._loop is live._loop
        live.stop_background()
        live.ensure_control_loop(timeout=2)
        assert live.out_queue is not old_queue
        assert live.audio.audio_in_queue is not old_audio
        assert live.session._send_lock is not old_lock
        assert live.audio.speaker.audio_in_queue is live.audio.audio_in_queue
        assert live.audio.mic.out_queue is live.vision.camera.out_queue is live.out_queue
        asyncio.run_coroutine_threadsafe(bind_queues(), live._loop).result(timeout=2)
        assert live.out_queue._loop is live._loop
        live.audio.start_output_only.assert_not_awaited()
        hearing.assert_not_called()
        client.assert_not_called()
    finally:
        live.stop_background()


def test_speech_start_can_be_promoted_to_hearing_once(monkeypatch):
    live = make_runtime(monkeypatch, backend="gemini")
    listener = SimpleNamespace(start=Mock(), stop=Mock())
    monkeypatch.setattr("kratos_agent.live.native_listener.get_native_hearing", Mock(return_value=listener))
    live.session.run_connection_loop = AsyncMock()

    async def exercise():
        await live.start(start_hearing=False)
        assert live.runtime_status()["speech_started"]
        assert not live.runtime_status()["hearing_started"]
        listener.start.assert_not_called()
        await live.start(start_hearing=True)
        await live.start(start_hearing=True)
        await asyncio.sleep(0)
        live.audio.start_output_only.assert_awaited_once()
        live.session.run_connection_loop.assert_awaited_once()
        listener.start.assert_called_once()
        await live.stop()
        assert not live.runtime_status()["speech_started"]
        assert not live.get_status().microphone_active

    asyncio.run(exercise())


def test_late_camera_start_is_observed_on_status_poll(monkeypatch):
    live = make_runtime(monkeypatch)

    async def exercise():
        opened = asyncio.Event()

        async def capture():
            await opened.wait()
            live.vision.camera.is_running = True
            await asyncio.Event().wait()

        live.vision.camera.run = capture
        live.vision.screen.health_check = Mock(side_effect=AssertionError("camera opened screen"))
        await live._start_control()
        await live.set_vision_mode("camera")
        assert not live.get_status().camera_active
        opened.set()
        await asyncio.sleep(0)
        assert live.get_status().camera_active
        assert live.get_status().camera_health == "online"
        await live.set_vision_mode("off")
        assert not live.get_status().camera_active
        await live.stop()

    asyncio.run(exercise())


def test_passive_status_observes_listener_failure_and_explicit_retry(monkeypatch):
    live = make_runtime(monkeypatch)
    listener = SimpleNamespace(is_running=True, start=Mock(), stop=Mock())
    listener.start.side_effect = lambda: setattr(listener, "is_running", True)
    live.native_hearing = listener
    live._hearing_started = True
    live.status_hub.update(microphone_active=True, microphone_health="online")
    factory = Mock(return_value=listener)
    monkeypatch.setattr("kratos_agent.live.native_listener.get_native_hearing", factory)
    live.vision.camera.run = AsyncMock(side_effect=AssertionError("status opened camera"))
    live.vision.screen.health_check = Mock(side_effect=AssertionError("status acquired screen"))

    listener.is_running = False
    status = live.get_status()
    assert not status.microphone_active and status.microphone_health == "error"
    assert not live.runtime_status()["hearing_started"]
    assert "Unmute to retry" in status.errors["speech_recognition"]
    assert live.get_status().errors["speech_recognition"] == status.errors["speech_recognition"]
    listener.start.assert_not_called()
    factory.assert_not_called()
    live.vision.camera.run.assert_not_awaited()
    live.vision.screen.health_check.assert_not_called()

    async def exercise():
        await live.start(start_hearing=True)
        assert live.get_status().microphone_active
        assert "speech_recognition" not in live.get_status().errors
        listener.start.assert_called_once()
        await live.stop()
        assert not live.get_status().microphone_active

    asyncio.run(exercise())


def test_capture_status_and_off_never_acquire_a_frame():
    async def exercise():
        hub = LiveStatusHub()
        vision = VisionManager(asyncio.Queue(), mode="none", status_hub=hub)
        vision.screen.health_check = Mock(side_effect=AssertionError("passive status captured screen"))
        vision.camera.run = AsyncMock(side_effect=AssertionError("Off opened camera"))
        assert not vision.get_capture_status()["capture_online"]
        hub.report_error("camera", "old camera error")
        hub.report_error("screen", "old screen error")
        status = await vision.set_mode("off")
        assert status["mode"] == "NONE" and status["error"] is None
        assert not hub.get_status().errors
        vision.mode = "camera"
        vision.camera.is_running = True
        assert vision.get_capture_status()["capture_online"]
        vision.screen.health_check.assert_not_called()
        vision.camera.run.assert_not_awaited()

    asyncio.run(exercise())


def test_receive_failure_propagates_to_connection_owner():
    async def exercise():
        session = make_session()

        async def failed_receive():
            raise ConnectionError("1006 transport closed")
            yield  # pragma: no cover

        session.is_running = True
        session.session = SimpleNamespace(receive=failed_receive)
        with pytest.raises(ConnectionError, match="1006"):
            await session.receive_loop()

    asyncio.run(exercise())


def test_immediate_socket_failures_back_off_and_clear_connected(monkeypatch):
    session = make_session()
    delays = []
    connected_states = []
    session.status_hub.subscribe(lambda status: connected_states.append(status.gemini_connected))

    async def failed_receive():
        raise ConnectionError("1011 internal error private-test-credential")
        yield  # pragma: no cover

    @asynccontextmanager
    async def connect(**_kwargs):
        yield SimpleNamespace(receive=failed_receive)

    close = AsyncMock()
    monkeypatch.setattr("kratos_agent.live.session.genai.Client", Mock(return_value=SimpleNamespace(
        aio=SimpleNamespace(live=SimpleNamespace(connect=connect), aclose=close),
    )))

    async def backoff(delay):
        delays.append(delay)
        assert session.session is None
        assert not session.status_hub.get_status().gemini_connected
        if len(delays) == 6:
            session.is_running = False

    monkeypatch.setattr("kratos_agent.live.session.asyncio.sleep", backoff)
    asyncio.run(session.run_connection_loop())
    assert delays == [1, 2, 4, 8, 15, 15]
    assert True in connected_states and connected_states[-1] is False
    assert not session.is_running and not session.get_diagnostics()["connected"]
    assert "private-test-credential" not in session.status_hub.get_status().last_error
    close.assert_awaited_once()


def test_empty_receive_stream_retries_instead_of_spinning(monkeypatch):
    session = make_session()

    async def empty_receive():
        if False:
            yield

    @asynccontextmanager
    async def connect(**_kwargs):
        yield SimpleNamespace(receive=empty_receive)

    close = AsyncMock()
    monkeypatch.setattr("kratos_agent.live.session.genai.Client", Mock(return_value=SimpleNamespace(
        aio=SimpleNamespace(live=SimpleNamespace(connect=connect), aclose=close),
    )))
    delays = []

    async def backoff(delay):
        delays.append(delay)
        session.is_running = False

    monkeypatch.setattr("kratos_agent.live.session.asyncio.sleep", backoff)
    asyncio.run(session.run_connection_loop())
    assert delays == [1]
    assert "closed without a response" in session.status_hub.get_status().last_error
    close.assert_awaited_once()


def test_idle_speech_socket_remains_healthy_without_response_heartbeat():
    async def exercise():
        session = make_session()
        session.is_running = True
        session.session = object()
        session._last_heartbeat = time.time() - 3600
        receiver = asyncio.create_task(asyncio.Event().wait(), name="kratos-live-speech-recv")
        session._tasks = [receiver]
        assert session.is_healthy()
        await session.stop()
        assert not session.is_healthy()

    asyncio.run(exercise())


def test_client_setup_failure_resets_status_and_redacts_credentials(monkeypatch):
    session = make_session()
    session.status_hub.update(gemini_connected=True)
    monkeypatch.setattr("kratos_agent.live.session.genai.Client", Mock(side_effect=RuntimeError(
        "rejected private-test-credential",
    )))
    asyncio.run(session.run_connection_loop())
    assert not session.is_running and not session.status_hub.get_status().gemini_connected
    assert session.status_hub.get_status().live_health == "offline"
    assert "private-test-credential" not in session.status_hub.get_status().last_error


def test_cancelling_connection_waits_for_transport_cleanup(monkeypatch):
    session = make_session()

    async def exercise():
        receiving = asyncio.Event()
        cleanup = []

        async def receive():
            receiving.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover

        @asynccontextmanager
        async def connect(**_kwargs):
            try:
                yield SimpleNamespace(receive=receive)
            finally:
                cleanup.append("transport")

        async def close():
            cleanup.append("client")

        monkeypatch.setattr("kratos_agent.live.session.genai.Client", Mock(return_value=SimpleNamespace(
            aio=SimpleNamespace(live=SimpleNamespace(connect=connect), aclose=close),
        )))
        task = asyncio.create_task(session.run_connection_loop())
        await asyncio.wait_for(receiving.wait(), timeout=2)
        task.cancel()
        await asyncio.wait_for(task, timeout=2)
        assert cleanup == ["transport", "client"]
        assert not session._tasks and session.session is None
        assert not session.status_hub.get_status().gemini_connected

    asyncio.run(exercise())
