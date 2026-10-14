"""Explicit profile controls start only their own required Live components."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.error import HTTPError

import pytest
from test_studio_web import call, server as shared_server

from kratos_agent.live.config import LiveConfig
from kratos_agent.live.runtime import LiveRuntime

server = shared_server


@pytest.fixture
def profile_live(monkeypatch):
    audio = SimpleNamespace(start_output_only=AsyncMock(), stop=AsyncMock(), mute=Mock(), unmute=Mock())
    monkeypatch.setattr("kratos_agent.live.runtime.AudioManager", lambda **kwargs: audio)
    live = LiveRuntime(config=LiveConfig(api_key="", backend="native", enabled=True, video_mode="none"))
    audio.mute.side_effect = lambda: live.status_hub.update(muted=True)
    audio.unmute.side_effect = lambda: live.status_hub.update(muted=False)
    live.vision.stop = AsyncMock()

    async def set_mode(mode):
        live.vision.mode = "none" if mode == "off" else mode
        live.vision.camera.is_running = mode == "camera"
        live.vision.screen.is_running = mode == "screen"
        live.status_hub.update(video_mode="none" if mode == "off" else mode,
                               camera_active=mode == "camera", screen_active=mode == "screen")
        return {"mode": mode}

    live.vision.set_mode = AsyncMock(side_effect=set_mode)
    live.vision.get_capture_status = Mock(return_value={"mode": "none"})
    hearing = SimpleNamespace(start=Mock(), stop=Mock(), mute=Mock(), unmute=Mock())
    monkeypatch.setattr("kratos_agent.live.native_listener.get_native_hearing", Mock(return_value=hearing))
    monkeypatch.setattr("kratos_agent.live.get_live_runtime", lambda: live)
    monkeypatch.setenv("KRATOS_DISABLE_LIVE", "1")
    monkeypatch.setenv("KRATOS_PROFILE_WORKER_ID", "a" * 32)
    yield live, audio, hearing
    live.stop_background()


def test_status_does_not_start_media_or_control_loop(server, profile_live):
    live, audio, hearing = profile_live
    status = json.load(call(server, "/api/live/status"))
    assert status["runtime_started"] is False
    assert status["autostart_deferred"] is True
    assert status["speech_backend"] == "native"
    assert live._loop is None
    hearing.start.assert_not_called()
    audio.start_output_only.assert_not_called()


def test_explicit_vision_starts_profile_loop_without_speech_or_mic(server, profile_live):
    live, audio, hearing = profile_live
    status = json.load(call(server, "/api/live/control", {"action": "set_vision_mode", "value": "camera"}))
    assert status["runtime_started"] is True and status["speech_started"] is False
    assert status["camera_active"] is True
    assert live._loop.is_running()
    live.vision.set_mode.assert_awaited_once_with("camera")
    hearing.start.assert_not_called()
    audio.start_output_only.assert_not_called()
    off = json.load(call(server, "/api/live/control", {"action": "set_vision_mode", "value": "off"}))
    assert off["camera_active"] is False and off["video_mode"] == "none"


def test_reconnect_starts_speech_with_microphone_muted(server, profile_live):
    live, _, hearing = profile_live
    status = json.load(call(server, "/api/live/control", {"action": "reconnect"}))
    # Runtime startup may be scheduled; the status endpoint observes it shortly.
    live.ensure_control_loop(timeout=2)
    assert status["muted"] is True
    hearing.start.assert_not_called()
    status = json.load(call(server, "/api/live/control", {"action": "unmute"}))
    assert status["speech_started"] is True and status["muted"] is False
    hearing.start.assert_called_once()


def test_disabled_speech_keeps_vision_available(server, profile_live):
    live, _, hearing = profile_live
    live.config.enabled = False
    with pytest.raises(HTTPError) as failure:
        call(server, "/api/live/control", {"action": "unmute"})
    assert failure.value.code == 503
    hearing.start.assert_not_called()
    status = json.load(call(server, "/api/live/control", {"action": "set_vision_mode", "value": "off"}))
    assert status["runtime_started"] is True and status["speech_enabled"] is False


def test_failed_startup_returns_actionable_service_error(server, profile_live, monkeypatch):
    live, _, _ = profile_live
    monkeypatch.setattr(live, "ensure_control_loop", Mock(side_effect=TimeoutError()))
    with pytest.raises(HTTPError) as failure:
        call(server, "/api/live/control", {"action": "set_vision_mode", "value": "camera"})
    assert failure.value.code == 503
    assert "timed out" in json.load(failure.value)["error"]


def test_overlapping_live_controls_are_rejected(server, profile_live):
    server.live_control_lock.acquire()
    try:
        with pytest.raises(HTTPError) as failure:
            call(server, "/api/live/control", {"action": "mute"})
        assert failure.value.code == 409
    finally:
        server.live_control_lock.release()
