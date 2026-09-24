"""Unit and integration tests for Kratos Multimodal Live subsystem."""
import asyncio
import io
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from kratos_agent.core.runtime_contracts import EventKind, RuntimeEvent
from kratos_agent.live.audio import AudioManager
from kratos_agent.live.bridge import KratosBridge
from kratos_agent.live.camera import CameraCapture
from kratos_agent.live.config import LiveConfig
from kratos_agent.live.events import LiveState, LiveStatus, LiveStatusHub
from kratos_agent.live.microphone import MicrophoneListener, _calculate_rms, get_input_devices
from kratos_agent.live.narration import NarrationManager, sanitize_speech_text
from kratos_agent.live.router import IntentKind, LiveRouter
from kratos_agent.live.runtime import LiveRuntime
from kratos_agent.live.screen import ScreenCapture
from kratos_agent.live.session import LiveSession
from kratos_agent.live.speaker import SpeakerPlayer
from kratos_agent.live.vision import VisionManager


class TestLiveConfig(unittest.TestCase):
    def test_config_defaults(self):
        cfg = LiveConfig(api_key="test-key")
        self.assertEqual(cfg.api_key, "test-key")
        self.assertEqual(cfg.send_sample_rate, 16000)
        self.assertEqual(cfg.receive_sample_rate, 24000)
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.is_valid())

    def test_config_invalid_without_key(self):
        cfg = LiveConfig(api_key="", enabled=True)
        self.assertFalse(cfg.is_valid())

    def test_config_invalid_when_disabled(self):
        cfg = LiveConfig(api_key="test-key", enabled=False)
        self.assertFalse(cfg.is_valid())


class TestLiveEvents(unittest.TestCase):
    def test_status_hub_update_and_subscribe(self):
        hub = LiveStatusHub()
        received = []

        def listener(status: LiveStatus):
            received.append(status.gemini_connected)

        hub.subscribe(listener)
        hub.update(gemini_connected=True)

        self.assertTrue(hub.get_status().gemini_connected)
        self.assertEqual(received, [True])

        hub.unsubscribe(listener)
        hub.update(gemini_connected=False)
        self.assertEqual(received, [True])  # Not called after unsubscribe


class TestSanitizeSpeechText(unittest.TestCase):
    def test_redacts_api_keys_and_tokens(self):
        raw = "My API_KEY is AIzaSyD9876543210123456789012345678901 and token: sk-1234567890123456789012345"
        sanitized = sanitize_speech_text(raw)
        self.assertNotIn("AIzaSyD", sanitized)
        self.assertNotIn("sk-123456", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_strips_html_tags(self):
        raw = "<think>internal reasoning</think> Task completed."
        sanitized = sanitize_speech_text(raw)
        self.assertNotIn("<think>", sanitized)
        self.assertIn("Task completed.", sanitized)


class TestNarrationManager(unittest.TestCase):
    def test_narrates_task_events(self):
        spoken = []
        mgr = NarrationManager(send_speech_fn=lambda text: spoken.append(text), min_interval_seconds=0.0)
        mgr.is_active = True

        event = RuntimeEvent(kind=EventKind.PLANNING_STARTED, payload={})
        mgr.on_event(event)
        self.assertTrue(any("planning" in s.lower() for s in spoken))

        event_done = RuntimeEvent(kind=EventKind.TURN_COMPLETED, payload={"status": "completed"})
        mgr.on_event(event_done)
        self.assertTrue(any("completed" in s.lower() for s in spoken))

    def test_throttling_prevents_rapid_chatter(self):
        spoken = []
        mgr = NarrationManager(send_speech_fn=lambda text: spoken.append(text), min_interval_seconds=10.0)
        mgr.is_active = True

        mgr.on_event(RuntimeEvent(kind=EventKind.TOOL_CALL_STARTED, payload={"name": "read_file"}))
        self.assertEqual(len(spoken), 1)

        # Immediate second non-priority event should be throttled
        mgr.on_event(RuntimeEvent(kind=EventKind.TOOL_CALL_STARTED, payload={"name": "grep_search"}))
        self.assertEqual(len(spoken), 1)


class TestKratosBridge(unittest.IsolatedAsyncioTestCase):
    async def test_submit_task_executes_runtime(self):
        mock_runtime = MagicMock()
        mock_runtime.run_agent.return_value = "Success output from Kratos"

        hub = LiveStatusHub()
        bridge = KratosBridge(runtime=mock_runtime, status_hub=hub)

        res = await bridge.submit_task("Fix the bug", visual_context="Error on screen")
        self.assertEqual(res["status"], "started")
        self.assertIn("task_id", res)

    async def test_cancels_active_task(self):
        mock_runtime = MagicMock()
        bridge = KratosBridge(runtime=mock_runtime)
        bridge.active_task_id = "task-123"

        res = bridge.cancel_active_task()
        self.assertEqual(res["status"], "cancelled")
        self.assertIsNone(bridge.active_task_id)
        mock_runtime.cancel.assert_called_once()

    async def test_busy_guard(self):
        mock_runtime = MagicMock()
        bridge = KratosBridge(runtime=mock_runtime)
        bridge.active_task_id = "task-existing"
        bridge.active_task_desc = "Running tests"

        res = await bridge.submit_task("Do new thing", force=False)
        self.assertEqual(res["status"], "busy")
        self.assertIn("already working", res["message"])


class TestLiveRouter(unittest.IsolatedAsyncioTestCase):
    async def test_tool_declarations(self):
        bridge = MagicMock()
        router = LiveRouter(bridge=bridge)
        tools = router.get_tool_declarations()

        self.assertEqual(len(tools), 1)
        fns = [fn.name for fn in tools[0].function_declarations]
        self.assertIn("start_agent_task", fns)
        self.assertIn("cancel_active_task", fns)
        self.assertIn("get_task_status", fns)

    async def test_handle_tool_call_start_task(self):
        bridge = AsyncMock()
        bridge.submit_task.return_value = {"status": "completed"}
        router = LiveRouter(bridge=bridge)

        res = await router.handle_tool_call("start_agent_task", {"task_description": "Run tests", "visual_context": "traceback"})
        self.assertEqual(res["status"], "completed")
        bridge.submit_task.assert_awaited_once_with("Run tests", visual_context="traceback")

    async def test_handle_tool_call_cancel(self):
        bridge = MagicMock()
        bridge.cancel_active_task.return_value = {"status": "cancelled"}
        router = LiveRouter(bridge=bridge)

        res = await router.handle_tool_call("cancel_active_task", {})
        self.assertEqual(res["status"], "cancelled")
        bridge.cancel_active_task.assert_called_once()

    def test_classify_intent_fallback(self):
        router = LiveRouter(bridge=MagicMock())
        self.assertEqual(router.classify_intent_fallback("Stop!"), IntentKind.CANCEL)
        self.assertEqual(router.classify_intent_fallback("What are you doing?"), IntentKind.STATUS)
        self.assertEqual(router.classify_intent_fallback("What is on my screen?"), IntentKind.VISION)
        self.assertEqual(router.classify_intent_fallback("Fix the auth bug in login.py"), IntentKind.AGENT_TASK)
        self.assertEqual(router.classify_intent_fallback("Hello there"), IntentKind.CHAT)



class TestLiveExtendedThinkingContract(unittest.IsolatedAsyncioTestCase):
    async def test_live_tools_are_non_blocking_for_extended_thinking(self):
        router = LiveRouter(bridge=MagicMock())
        tools = router.get_tool_declarations()
        declarations = tools[0].function_declarations
        self.assertTrue(declarations)
        for declaration in declarations:
            self.assertTrue(str(getattr(declaration, "behavior", "")).endswith("NON_BLOCKING"))

    def test_interaction_status_normalization(self):
        self.assertEqual(LiveSession._normalize_interaction_status("IN_PROGRESS"), "IN_PROGRESS")
        self.assertEqual(LiveSession._normalize_interaction_status("idle"), "IDLE")
        self.assertIsNone(LiveSession._normalize_interaction_status(None))

    def test_interaction_status_extraction(self):
        response = MagicMock()
        response.interaction_status = "IN_PROGRESS"
        self.assertEqual(LiveSession._extract_interaction_status(response), "IN_PROGRESS")


class TestLiveErrorIsolation(unittest.TestCase):
    def test_component_errors_are_retained_independently(self):
        hub = LiveStatusHub()
        hub.report_error("gemini", "Live connection failed")
        hub.report_error("microphone", "Microphone access denied")
        status = hub.get_status()
        self.assertEqual(status.last_error_component, "microphone")
        self.assertEqual(status.errors["gemini"], "Live connection failed")
        self.assertEqual(status.errors["microphone"], "Microphone access denied")


class TestLiveRouterCaptureFailure(unittest.IsolatedAsyncioTestCase):
    async def test_observe_none_is_reported_as_failure(self):
        router = LiveRouter(bridge=MagicMock(), capture_screen_handler=AsyncMock(return_value=None))
        result = await router.handle_tool_call("observe", {"reason": "test"})
        self.assertEqual(result["status"], "error")


class TestAudioMuteSemantics(unittest.TestCase):
    def test_voice_mute_only_mutes_microphone(self):
        audio = AudioManager(out_queue=asyncio.Queue())
        audio.speaker.is_muted = False
        audio.mute()
        self.assertTrue(audio.mic.is_muted)
        self.assertFalse(audio.speaker.is_muted)

class TestSpeakerPlayer(unittest.TestCase):
    def test_clear_flushes_queue(self):
        q = asyncio.Queue()
        q.put_nowait(b"audio_chunk_1")
        q.put_nowait(b"audio_chunk_2")

        spk = SpeakerPlayer(audio_in_queue=q)
        self.assertEqual(q.qsize(), 2)

        spk.clear()
        self.assertEqual(q.qsize(), 0)

    def test_mute_clears_queue(self):
        q = asyncio.Queue()
        q.put_nowait(b"audio_chunk_1")

        spk = SpeakerPlayer(audio_in_queue=q)
        spk.mute()
        self.assertTrue(spk.is_muted)
        self.assertEqual(q.qsize(), 0)


class TestAudioVisionErrorIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_microphone_failure_does_not_crash(self):
        q = asyncio.Queue()
        mic = MicrophoneListener(out_queue=q)

        # Simulate exception in stream open
        with patch("sounddevice.RawInputStream", side_effect=RuntimeError("No microphone found")):
            await mic.run()
            self.assertFalse(mic.is_running)
        mic.stop()

    async def test_camera_failure_does_not_crash(self):
        q = asyncio.Queue()
        cam = CameraCapture(out_queue=q)

        # Simulate camera open failure
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        with patch("cv2.VideoCapture", return_value=mock_cap):
            await cam.run()
            self.assertFalse(cam.is_running)
        cam.stop()

    async def test_vision_manager_mode_switching(self):
        q = asyncio.Queue()
        vm = VisionManager(out_queue=q, mode="none")
        await vm.start()
        self.assertEqual(vm.mode, "none")

        with patch.object(vm.camera, "run", new_callable=AsyncMock), \
             patch.object(vm.screen, "run", new_callable=AsyncMock):
            await vm.set_mode("screen")
            self.assertEqual(vm.mode, "screen")

            await vm.set_mode("both")
            self.assertEqual(vm.mode, "both")

            await vm.stop()
        await vm.stop()


class TestLiveRuntimeLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_start_stop(self):
        cfg = LiveConfig(api_key="mock-key", enabled=True)
        rt = LiveRuntime(config=cfg)

        with patch.object(rt.audio, "start", new_callable=AsyncMock), \
             patch.object(rt.vision, "start", new_callable=AsyncMock), \
             patch.object(rt.session, "run_connection_loop", new_callable=AsyncMock):
            await rt.start()
            self.assertTrue(rt._is_running)

            await rt.stop()
            self.assertFalse(rt._is_running)

    async def test_runtime_without_key_keeps_control_loop_ready_but_does_not_open_audio(self):
        cfg = LiveConfig(api_key="", enabled=True)
        rt = LiveRuntime(config=cfg)

        with patch.object(rt.audio, "start", new_callable=AsyncMock) as audio_start, \
             patch.object(rt.vision, "start", new_callable=AsyncMock) as vision_start, \
             patch.object(rt.session, "run_connection_loop", new_callable=AsyncMock) as session_start:
            await rt.start()
            self.assertTrue(rt._is_running)
            self.assertIs(asyncio.get_running_loop(), rt._loop)
            self.assertIn("API_KEY", rt.get_status().last_error or "")
            audio_start.assert_not_awaited()
            vision_start.assert_not_awaited()
            session_start.assert_not_awaited()

            await rt.set_vision_mode("none")
            await rt.stop()
            self.assertFalse(rt._is_running)


class TestMicrophoneAndVAD(unittest.TestCase):
    def test_calculate_rms_silence_and_signal(self):
        # 1. Complete silence (zeros)
        silence = b"\x00\x00" * 512
        self.assertEqual(_calculate_rms(silence), 0)

        # 2. Synthetic signal with known amplitude
        # Alternating +1000 and -1000
        signal = b"".join(int(1000 if i % 2 == 0 else -1000).to_bytes(2, byteorder="little", signed=True) for i in range(512))
        rms = _calculate_rms(signal)
        self.assertEqual(rms, 1000)

    def test_get_input_devices_enumeration(self):
        mock_devices = [
            {"name": "Intel Smart Sound Mic", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 16000},
            {"name": "Realtek Output Speaker", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
            {"name": "USB Headset Mic", "max_input_channels": 1, "hostapi": 1, "default_samplerate": 16000},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices), \
             patch("sounddevice.default.device", [0, 1]):
            devs = get_input_devices()
            self.assertEqual(len(devs), 2)
            self.assertEqual(devs[0]["name"], "Intel Smart Sound Mic")
            self.assertTrue(devs[0]["is_default"])
            self.assertEqual(devs[1]["name"], "USB Headset Mic")
            self.assertFalse(devs[1]["is_default"])

    def test_device_selection_resolution(self):
        mock_devices = [
            {"name": "Intel Smart Sound Mic", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 16000},
            {"name": "USB Headset Microphone", "max_input_channels": 1, "hostapi": 1, "default_samplerate": 16000},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices), \
             patch("sounddevice.default.device", [0, 1]):
            q = asyncio.Queue()

            # Index matching
            mic_by_idx = MicrophoneListener(out_queue=q, device=1)
            idx, name = mic_by_idx._resolve_device()
            self.assertEqual(idx, 1)
            self.assertEqual(name, "USB Headset Microphone")

            # Substring matching
            mic_by_name = MicrophoneListener(out_queue=q, device="intel")
            idx, name = mic_by_name._resolve_device()
            self.assertEqual(idx, 0)
            self.assertEqual(name, "Intel Smart Sound Mic")

            # Fallback to default
            mic_fallback = MicrophoneListener(out_queue=q, device="nonexistent")
            idx, name = mic_fallback._resolve_device()
            self.assertEqual(idx, 0)

    def test_vad_speech_start_and_stop(self):
        q = asyncio.Queue()
        speech_started = []
        speech_stopped = []

        mic = MicrophoneListener(
            out_queue=q,
            vad_threshold=400,
            vad_silence_seconds=0.1,
            on_speech_started=lambda: speech_started.append(True),
            on_speech_stopped=lambda: speech_stopped.append(True),
        )

        loud_chunk = b"".join(int(800 if i % 2 == 0 else -800).to_bytes(2, byteorder="little", signed=True) for i in range(512))
        silent_chunk = b"\x00\x00" * 512

        # 1. Loud audio chunk triggers speech started
        mic._process_audio_chunk(loud_chunk)
        self.assertTrue(mic.is_user_speaking)
        self.assertEqual(len(speech_started), 1)

        # 2. Silence chunk before timeout does not trigger speech stopped
        mic._process_audio_chunk(silent_chunk)
        self.assertTrue(mic.is_user_speaking)
        self.assertEqual(len(speech_stopped), 0)

        # 3. Wait for silence duration to elapse
        time.sleep(0.12)
        mic._process_audio_chunk(silent_chunk)
        self.assertFalse(mic.is_user_speaking)
        self.assertEqual(len(speech_stopped), 1)

    def test_instant_interruption_when_assistant_speaking(self):
        q = asyncio.Queue()
        hub = LiveStatusHub()
        hub.update(current_state=LiveState.SPEAKING)

        audio_mgr = AudioManager(out_queue=q, status_hub=hub, vad_threshold=400)
        audio_mgr.speaker.is_running = True
        audio_mgr.speaker.audio_in_queue.put_nowait(b"queued_speech")

        loud_chunk = b"".join(int(900 if i % 2 == 0 else -900).to_bytes(2, byteorder="little", signed=True) for i in range(512))

        # Processing loud chunk while assistant is speaking must trigger immediate interruption
        audio_mgr.mic._process_audio_chunk(loud_chunk)

        # Speaker queue must be emptied and state must transition to LISTENING
        self.assertTrue(audio_mgr.speaker.audio_in_queue.empty())
        self.assertEqual(hub.get_status().current_state, LiveState.LISTENING)

    def test_microphone_open_error_updates_status_gracefully(self):
        q = asyncio.Queue()
        hub = LiveStatusHub()
        mic = MicrophoneListener(out_queue=q, status_hub=hub)

        with patch("sounddevice.RawInputStream", side_effect=PermissionError("Microphone access denied")):
            asyncio.run(mic.run())

        self.assertFalse(mic.is_running)
        self.assertFalse(hub.get_status().microphone_active)
        self.assertIn("PermissionError", str(hub.get_status().last_error) or "")


if __name__ == "__main__":
    unittest.main()
