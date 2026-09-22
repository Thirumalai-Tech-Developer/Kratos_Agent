"""Unit tests for UserOutputFilter and OutputAggregator."""
from __future__ import annotations
import unittest

from kratos_agent.events.models import AgentEvent, EventType
from kratos_agent.output.user_output import OutputMode, UserOutputFilter
from kratos_agent.output.aggregator import OutputAggregator


class TestUserOutput(unittest.TestCase):
    def setUp(self) -> None:
        self.normal_filter = UserOutputFilter(OutputMode.NORMAL)
        self.debug_filter = UserOutputFilter(OutputMode.DEBUG)
        self.silent_filter = UserOutputFilter(OutputMode.SILENT)
        self.aggregator = OutputAggregator()

    def test_normal_mode_visibility(self) -> None:
        # User-visible events
        self.assertTrue(self.normal_filter.should_display(AgentEvent(type=EventType.TASK_STARTED)))
        self.assertTrue(self.normal_filter.should_display(AgentEvent(type=EventType.MILESTONE)))
        self.assertTrue(self.normal_filter.should_display(AgentEvent(type=EventType.TASK_COMPLETED)))

        # Internal events hidden in normal mode
        self.assertFalse(self.normal_filter.should_display(AgentEvent(type=EventType.ACTION_STARTED)))
        self.assertFalse(self.normal_filter.should_display(AgentEvent(type=EventType.DEBUG)))
        self.assertFalse(self.normal_filter.should_display(AgentEvent(type=EventType.TOOL_OUTPUT)))
        self.assertFalse(self.normal_filter.should_display(AgentEvent(type=EventType.VERIFICATION_STARTED)))

    def test_debug_mode_shows_everything(self) -> None:
        self.assertTrue(self.debug_filter.should_display(AgentEvent(type=EventType.ACTION_STARTED)))
        self.assertTrue(self.debug_filter.should_display(AgentEvent(type=EventType.DEBUG)))
        self.assertTrue(self.debug_filter.should_display(AgentEvent(type=EventType.TOOL_OUTPUT)))

    def test_silent_mode_shows_only_terminal(self) -> None:
        self.assertFalse(self.silent_filter.should_display(AgentEvent(type=EventType.MILESTONE)))
        self.assertTrue(self.silent_filter.should_display(AgentEvent(type=EventType.TASK_COMPLETED)))
        self.assertTrue(self.silent_filter.should_display(AgentEvent(type=EventType.TASK_FAILED)))

    def test_speech_filter_never_speaks_debug_or_internal(self) -> None:
        self.assertFalse(self.normal_filter.should_speak(AgentEvent(type=EventType.DEBUG)))
        self.assertFalse(self.normal_filter.should_speak(AgentEvent(type=EventType.ACTION_STARTED)))
        self.assertFalse(self.normal_filter.should_speak(AgentEvent(type=EventType.TOOL_OUTPUT)))
        self.assertTrue(self.normal_filter.should_speak(AgentEvent(type=EventType.TASK_STARTED)))
        self.assertTrue(self.normal_filter.should_speak(AgentEvent(type=EventType.TASK_COMPLETED)))

    def test_phrase_sanitization_and_deduplication(self) -> None:
        # Strips repetitive fluff (§16)
        p1 = self.aggregator.sanitize_phrase("I am currently opening Chrome.")
        self.assertEqual(p1, "Opening Chrome.")

        p2 = self.aggregator.sanitize_phrase("I'm running the automation script to find your walkthrough now.")
        self.assertEqual(p2, "The automation script to find your walkthrough now.")

        # Deduplication
        self.assertFalse(self.aggregator.is_duplicate("Opening Chrome."))
        self.assertTrue(self.aggregator.is_duplicate("Opening Chrome."))


if __name__ == "__main__":
    unittest.main()
