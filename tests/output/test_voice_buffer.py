"""Unit tests for VoiceBuffer and TTSQueue."""
from __future__ import annotations
import asyncio
import unittest

from kratos_agent.output.voice import VoiceBuffer, TTSQueue


class TestVoiceBuffer(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = VoiceBuffer(min_chars=20, max_chars=100)

    def test_fragment_buffering_no_early_flush(self) -> None:
        # Appending small fragments without punctuation should not flush
        self.buffer.append("I'm looking into the")
        self.assertIsNone(self.buffer.flush_sentence())

        self.buffer.append("relevant files to plan")
        self.assertIsNone(self.buffer.flush_sentence())

    def test_sentence_boundary_flush(self) -> None:
        self.buffer.append("I'm looking into the relevant files to plan.")
        sentence = self.buffer.flush_sentence()
        self.assertIsNotNone(sentence)
        self.assertEqual(sentence, "I'm looking into the relevant files to plan.")
        # Buffer is now empty
        self.assertIsNone(self.buffer.flush())

    def test_max_chars_overflow_split(self) -> None:
        long_text = "This is a very long clause that does not have any period or question mark and keeps going until it exceeds the max length"
        self.buffer.append(long_text)
        flushed = self.buffer.flush_sentence()
        self.assertIsNotNone(flushed)
        self.assertLessEqual(len(flushed), 100)

    def test_clear_buffer(self) -> None:
        self.buffer.append("Unfinished text...")
        self.buffer.clear()
        self.assertIsNone(self.buffer.flush())


class TestTTSQueue(unittest.IsolatedAsyncioTestCase):
    async def test_queue_and_cancellation(self) -> None:
        spoken = []

        async def fake_speak(text: str) -> None:
            await asyncio.sleep(0.05)
            spoken.append(text)

        queue = TTSQueue(speech_func=fake_speak)
        queue.enqueue("First sentence.")
        queue.enqueue("Second sentence.")

        # Cancel current speech & clear queue
        queue.cancel_current()
        self.assertTrue(queue._is_cancelled)


if __name__ == "__main__":
    unittest.main()
