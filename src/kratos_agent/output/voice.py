"""Batched sentence voice buffer and single-worker TTS queue."""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("kratos.voice")

MIN_TTS_CHARS = 35
MAX_TTS_CHARS = 240
SENTENCE_END_PATTERN = re.compile(r"[\.!\?\n]")


REASONING_PATTERNS = [
    re.compile(r"(?i)\bi'?m (looking into|checking|starting|running|confirming|currently|thinking|planning|inspecting)\b"),
    re.compile(r"(?i)\bi am (looking into|checking|starting|running|confirming|currently|thinking|planning|inspecting)\b"),
    re.compile(r"(?i)\bmy reasoning is\b"),
    re.compile(r"(?i)\bi decided to\b"),
    re.compile(r"(?i)\bchecking relevant files\b"),
    re.compile(r"(?i)\blet me check\b"),
    re.compile(r"(?i)\blet me look\b"),
    re.compile(r"(?i)\blet me inspect\b"),
    re.compile(r"(?i)\blet me think\b"),
]


def is_internal_reasoning(text: str) -> bool:
    """Detects whether text is an internal monologue/planning chunk that should NOT be spoken (§24, §43)."""
    if not text:
        return True
    t = text.strip()
    return any(p.search(t) for p in REASONING_PATTERNS)


class VoiceBuffer:
    """Buffers text chunks until a complete sentence or clause boundary is reached, filtering internal reasoning (§24, §43)."""

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

    def flush_sentence(self) -> str | None:
        """Flushes a complete sentence if one exists and passes internal reasoning filter."""
        if not self._buffer:
            return None

        # Check for sentence boundaries
        for match in SENTENCE_END_PATTERN.finditer(self._buffer):
            split_idx = match.end()
            sentence = self._buffer[:split_idx].strip()
            # If the sentence meets min_chars or buffer has reached max_chars
            if len(sentence) >= self.min_chars or len(self._buffer) >= self.max_chars:
                self._buffer = self._buffer[split_idx:].strip()
                if is_internal_reasoning(sentence):
                    logger.debug(f"[VoiceBuffer] Filtered internal reasoning: '{sentence}'")
                    return None
                return sentence

        # If buffer exceeds max_chars without punctuation, split at nearest whitespace
        if len(self._buffer) >= self.max_chars:
            space_idx = self._buffer.rfind(" ", self.min_chars, self.max_chars)
            if space_idx > 0:
                sentence = self._buffer[:space_idx].strip()
                self._buffer = self._buffer[space_idx:].strip()
                if is_internal_reasoning(sentence):
                    return None
                return sentence
            else:
                sentence = self._buffer[:self.max_chars].strip()
                self._buffer = self._buffer[self.max_chars:].strip()
                if is_internal_reasoning(sentence):
                    return None
                return sentence

        return None

    def flush(self) -> str | None:
        """Flushes all remaining text in the buffer, filtering internal reasoning."""
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining and not is_internal_reasoning(remaining):
            return remaining
        return None

    def clear(self) -> None:
        self._buffer = ""


class TTSQueue:
    """Asynchronous single-worker queue for serialized text-to-speech execution (§12, §13)."""

    def __init__(self, speech_func: Callable[[str], Any] | None = None) -> None:
        self.speech_func = speech_func
        self._queue: asyncio.Queue[str] | None = None
        self._worker_task: asyncio.Task | None = None
        self._current_speech_task: asyncio.Task | None = None
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


_voice_buffer: VoiceBuffer | None = None
_tts_queue: TTSQueue | None = None


def sanitize_speech_text(text: str) -> str:
    """Sanitizes text removing internal jargon, URLs, and code blocks for speech output."""
    from .native_voice import clean_text_for_speech
    return clean_text_for_speech(text)


def get_voice_buffer() -> VoiceBuffer:
    global _voice_buffer
    if _voice_buffer is None:
        _voice_buffer = VoiceBuffer()
    return _voice_buffer


def get_tts_queue() -> TTSQueue:
    global _tts_queue
    if _tts_queue is None:
        def _speak_handler(text: str) -> None:
            try:
                from kratos_agent.live import get_live_runtime
                get_live_runtime().speak(text)
            except Exception:
                try:
                    from .native_voice import get_native_voice
                    get_native_voice().speak(text)
                except Exception:
                    pass
        _tts_queue = TTSQueue(speech_func=_speak_handler)
    return _tts_queue
