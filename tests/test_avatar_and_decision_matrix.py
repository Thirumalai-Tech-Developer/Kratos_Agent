"""Unit tests for the 6-priority decision matrix, on-demand vision, and floating avatar."""
import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock

from kratos_agent.live.events import LiveState, LiveStatus, LiveStatusHub
from kratos_agent.live.router import LiveRouter, IntentKind, StructuredTask
from kratos_agent.live.avatar import FloatingAvatar, _make_circular_avatar, STATE_COLORS
from kratos_agent.live.vision import VisionManager


class TestAvatarAndDecisionMatrix(unittest.TestCase):
    def test_live_state_transitions(self):
        hub = LiveStatusHub()
        states_recorded = []

        hub.subscribe(lambda st: states_recorded.append(st.current_state))

        hub.update(current_state=LiveState.CONNECTING)
        hub.update(current_state=LiveState.IDLE)
        hub.update(current_state=LiveState.LISTENING)
        hub.update(current_state=LiveState.THINKING)
        hub.update(current_state=LiveState.EXECUTING)
        hub.update(current_state=LiveState.SPEAKING)
        hub.update(current_state=LiveState.ERROR)
        hub.update(current_state=LiveState.RECONNECTING)

        self.assertEqual(states_recorded, [
            LiveState.CONNECTING,
            LiveState.IDLE,
            LiveState.LISTENING,
            LiveState.THINKING,
            LiveState.EXECUTING,
            LiveState.SPEAKING,
            LiveState.ERROR,
            LiveState.RECONNECTING,
        ])

    def test_decision_matrix_conversational(self):
        mock_bridge = MagicMock()
        router = LiveRouter(bridge=mock_bridge)

        # Pure informational
        t1 = router.evaluate_request("What is Docker?")
        self.assertEqual(t1.intent, IntentKind.CHAT)

        t2 = router.evaluate_request("Explain how Python virtual environments work.")
        self.assertEqual(t2.intent, IntentKind.CHAT)

        # Explicit conversational overrides action words
        t3 = router.evaluate_request("Just explain how to fix this bug.")
        self.assertEqual(t3.intent, IntentKind.CHAT)

        t4 = router.evaluate_request("Don't change anything, only explain the code.")
        self.assertEqual(t4.intent, IntentKind.CHAT)

    def test_decision_matrix_actionable(self):
        mock_bridge = MagicMock()
        router = LiveRouter(bridge=mock_bridge)

        t1 = router.evaluate_request("Create a Python script that monitors CPU usage.")
        self.assertEqual(t1.intent, IntentKind.AGENT_TASK)

        t2 = router.evaluate_request("Run the unit tests and tell me if they pass.")
        self.assertEqual(t2.intent, IntentKind.AGENT_TASK)

        t3 = router.evaluate_request("Install the missing numpy dependency.")
        self.assertEqual(t3.intent, IntentKind.AGENT_TASK)

    def test_decision_matrix_context_resolution(self):
        mock_bridge = MagicMock()
        router = LiveRouter(bridge=mock_bridge)

        # Ambiguous reference without context -> CLARIFY
        t1 = router.evaluate_request("Fix that.")
        self.assertEqual(t1.intent, IntentKind.CLARIFY)
        self.assertIn("Which file", t1.clarification_question or "")

        # Context supplied -> resolved AGENT_TASK
        t2 = router.evaluate_request("Fix that.", recent_context="Found error in server.py line 42")
        self.assertEqual(t2.intent, IntentKind.AGENT_TASK)
        self.assertIn("server.py line 42", t2.task)

    def test_decision_matrix_destructive_safety(self):
        mock_bridge = MagicMock()
        router = LiveRouter(bridge=mock_bridge)

        t1 = router.evaluate_request("Delete all files in the project.")
        self.assertEqual(t1.intent, IntentKind.CONFIRM)
        self.assertTrue(t1.confirmation_required)
        self.assertIn("destructive", (t1.clarification_question or "").lower())

        t2 = router.evaluate_request("Drop database and permanently remove records.")
        self.assertEqual(t2.intent, IntentKind.CONFIRM)
        self.assertTrue(t2.confirmation_required)

    def test_decision_matrix_vision_requirement(self):
        mock_bridge = MagicMock()
        router = LiveRouter(bridge=mock_bridge)

        # Vision + Chat
        t1 = router.evaluate_request("Look at this and explain what you see.")
        self.assertEqual(t1.intent, IntentKind.VISION_CHAT)
        self.assertTrue(t1.vision_required)

        t2 = router.evaluate_request("What is this error on my screen?")
        self.assertEqual(t2.intent, IntentKind.VISION_CHAT)
        self.assertTrue(t2.vision_required)

        # Vision + Actionable task
        t3 = router.evaluate_request("Look at this error and fix it.")
        self.assertEqual(t3.intent, IntentKind.VISION_AGENT_TASK)
        self.assertTrue(t3.vision_required)

        t4 = router.evaluate_request("Fix this error on my screen.")
        self.assertEqual(t4.intent, IntentKind.VISION_AGENT_TASK)
        self.assertTrue(t4.vision_required)

    def test_decision_matrix_control_commands(self):
        mock_bridge = MagicMock()
        router = LiveRouter(bridge=mock_bridge)

        self.assertEqual(router.evaluate_request("stop").intent, IntentKind.CANCEL)
        self.assertEqual(router.evaluate_request("cancel active task").intent, IntentKind.CANCEL)
        self.assertEqual(router.evaluate_request("abort").intent, IntentKind.CANCEL)
        self.assertEqual(router.evaluate_request("what are you doing?").intent, IntentKind.STATUS)
        self.assertEqual(router.evaluate_request("task status").intent, IntentKind.STATUS)

    def test_router_tool_declarations_and_dispatch(self):
        async def _run():
            mock_bridge = MagicMock()
            mock_bridge.submit_task = AsyncMock(return_value={"status": "completed", "result": "done"})
            mock_bridge.cancel_active_task = MagicMock(return_value={"status": "cancelled"})
            mock_bridge.get_status = MagicMock(return_value={"is_busy": False})

            screen_captured = False

            async def mock_capture_screen():
                nonlocal screen_captured
                screen_captured = True
                return b"fake_screen_jpeg"

            router = LiveRouter(bridge=mock_bridge, capture_screen_handler=mock_capture_screen)
            tools = router.get_tool_declarations()

            self.assertEqual(len(tools), 1)
            fn_names = [fn.name for fn in tools[0].function_declarations]
            self.assertIn("start_agent_task", fn_names)
            self.assertIn("capture_screen_context", fn_names)
            self.assertIn("cancel_active_task", fn_names)
            self.assertIn("get_task_status", fn_names)

            # Test capture_screen_context tool dispatch
            res = await router.handle_tool_call("capture_screen_context", {"reason": "Test inspection"})
            self.assertEqual(res["status"], "success")
            self.assertTrue(screen_captured)

            # Test start_agent_task dispatch
            res_task = await router.handle_tool_call("start_agent_task", {"task_description": "Write tests"})
            self.assertEqual(res_task["status"], "completed")

        asyncio.run(_run())

    def test_avatar_circular_generation(self):
        img = _make_circular_avatar("kratos-illu.png", 100)
        self.assertEqual(img.size, (100, 100))
        self.assertEqual(img.mode, "RGBA")

        # Verify fallback if file does not exist
        fallback = _make_circular_avatar("non_existent_file.png", 64)
        self.assertEqual(fallback.size, (64, 64))

    def test_avatar_state_palette(self):
        for state in LiveState:
            self.assertIn(state, STATE_COLORS)
            self.assertTrue(STATE_COLORS[state].startswith("#"))

    def test_avatar_dock_toggle(self):
        hub = LiveStatusHub()
        avatar = FloatingAvatar(
            image_path="kratos-illu.png",
            status_hub=hub,
        )

        self.assertFalse(avatar.is_docked)
        self.assertEqual(avatar.current_state, LiveState.CONNECTING)

        # Test status hub propagation to avatar
        hub.update(current_state=LiveState.LISTENING, last_transcript="Hello Kratos")
        self.assertEqual(avatar.current_state, LiveState.CONNECTING)  # Thread update scheduled via root.after


if __name__ == "__main__":
    unittest.main()
