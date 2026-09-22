"""Batched sentence voice buffer and single-worker TTS queue."""
from __future__ import annotations
import asyncio
import logging
import re
from typing import Any, Callable, List, Optional

logger = logging.getLogger("kratos.voice")

MIN_TTS_CHARS = 35
MAX_TTS_CHARS = 240
SENTENCE_END_PATTERN = re.compile(r"[\.!\?\n]")


class VoiceBuffer:
    """Buffers text chunks until a complete sentence or clause boundary is reached (§8, §9, §10, §11)."""

    def __init__(self, min_chars: int = MIN_TTS_CHARS, max_chars: int = MAX_TTS_CHARS) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self._buffer: str = ""

    def append(self, text: str) -> None:
        if not text:
            return
        if self._buffer and not self._buffer.endswith(" ") and not text.startswith(" "):
            self._buffer += " " + text.strip()
        else:
            self._buffer += text

    def flush_sentence(self) -> Optional[str]:
        """Flushes a complete sentence if one exists and meets length thresholds."""
        if not self._buffer:
            return None

        # Check for sentence boundaries
        match = SENTENCE_END_PATTERN.search(self._buffer)
        if match:
            split_idx = match.end()
            sentence = self._buffer[:split_idx].strip()
            # If the sentence meets min_chars or buffer has reached max_chars
            if len(sentence) >= self.min_chars or len(self._buffer) >= self.max_chars:
                self._buffer = self._buffer[split_idx:].strip()
                return sentence

        # If buffer exceeds max_chars without punctuation, split at nearest whitespace
        if len(self._buffer) >= self.max_chars:
            space_idx = self._buffer.rfind(" ", self.min_chars, self.max_chars)
            if space_idx > 0:
                sentence = self._buffer[:space_idx].strip()
                self._buffer = self._buffer[space_idx:].strip()
                return sentence
            else:
                sentence = self._buffer[:self.max_chars].strip()
                self._buffer = self._buffer[self.max_chars:].strip()
                return sentence

        return None

    def flush(self) -> Optional[str]:
        """Flushes all remaining text in the buffer."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining if remaining else None

    def clear(self) -> None:
        self._buffer = ""


class TTSQueue:
    """Asynchronous single-worker queue for serialized text-to-speech execution (§12, §13)."""

    def __init__(self, speech_func: Optional[Callable[[str], Any]] = None) -> None:
        self.speech_func = speech_func
        self._queue: Optional[asyncio.Queue[str]] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._current_speech_task: Optional[asyncio.Task] = None
        self._is_cancelled: bool = False

    def _ensure_queue(self) -> asyncio.Queue[str]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._ensure_queue()
            self._worker_task = asyncio.create_task(self._speech_worker())

    async def _speech_worker(self) -> None:
        q = self._ensure_queue()
        while True:
            try:
                text = await q.get()
                if self._is_cancelled:
                    q.task_done()
                    continue

                if self.speech_func:
                    try:
                        if asyncio.iscoroutinefunction(self.speech_func):
                            self._current_speech_task = asyncio.create_task(self.speech_func(text))
                            await self._current_speech_task
                        else:
                            self.speech_func(text)
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.warning(f"[TTSQueue] Speech execution error: {e}")
                    finally:
                        self._current_speech_task = None

                q.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[TTSQueue] Worker error: {e}")

    def enqueue(self, text: str) -> None:
        """Enqueues a complete sentence for speech."""
        if not text.strip():
            return
        self._is_cancelled = False
        q = self._ensure_queue()
        q.put_nowait(text.strip())
        self.start_worker()

    def cancel_current(self) -> None:
        """Cancels current speech and discards queued sentences on new tasks (§13)."""
        self._is_cancelled = True
        if self._current_speech_task and not self._current_speech_task.done():
            self._current_speech_task.cancel()
        self.clear_queue()

    def clear_queue(self) -> None:
        """Empties all pending voice queue items."""
        if self._queue is not None:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except Exception:
                    break


_voice_buffer: Optional[VoiceBuffer] = None
_tts_queue: Optional[TTSQueue] = None


def get_voice_buffer() -> VoiceBuffer:
    global _voice_buffer
    if _voice_buffer is None:
        _voice_buffer = VoiceBuffer()
    return _voice_buffer


def get_tts_queue() -> TTSQueue:
    global _tts_queue
    if _tts_queue is None:
        _tts_queue = TTSQueue()
    return _tts_queue
