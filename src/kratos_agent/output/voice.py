"""Speech directive sanitization and single-worker TTS queue."""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("kratos.voice")


class TTSQueue:
    """Asynchronous single-worker queue for serialized speech output."""

    def __init__(self, speech_func: Callable[[str], Any] | None = None) -> None:
        self.speech_func = speech_func
        self._queue: asyncio.Queue[str] | None = None
        self._worker_task: asyncio.Task | None = None
        self._current_speech_task: asyncio.Task | None = None
        self._is_cancelled = False

    def _ensure_queue(self) -> asyncio.Queue[str]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._ensure_queue()
            self._worker_task = asyncio.create_task(self._speech_worker())

    async def _speech_worker(self) -> None:
        queue = self._ensure_queue()
        while True:
            try:
                text = await queue.get()
                if self._is_cancelled:
                    queue.task_done()
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
                    except Exception as exc:
                        logger.warning("[TTSQueue] Speech execution error: %s", exc)
                    finally:
                        self._current_speech_task = None
                queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[TTSQueue] Worker error: %s", exc)

    def enqueue(self, text: str) -> None:
        """Enqueue text; the speech handler still requires a valid directive."""
        if not text.strip():
            return
        self._is_cancelled = False
        self._ensure_queue().put_nowait(text.strip())
        self.start_worker()

    def cancel_current(self) -> None:
        """Cancel current speech and discard pending items."""
        self._is_cancelled = True
        if self._current_speech_task and not self._current_speech_task.done():
            self._current_speech_task.cancel()
        self.clear_queue()

    def clear_queue(self) -> None:
        """Empty pending speech items."""
        if self._queue is not None:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except Exception:
                    break


_tts_queue: TTSQueue | None = None


def sanitize_speech_text(text: str) -> str:
    """Sanitize a speech-directive phrase before sending it to a voice backend."""
    text = str(text or "")
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|password|bearer)\s*(?:[:=]|\bis\b)\s*['\"]?[^\s'\"]+",
        "[REDACTED]",
        text,
    )
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,})\b", "[REDACTED]", text)
    text = re.sub(r"</?[^>]+>", "", text)
    from .native_voice import clean_text_for_speech
    return clean_text_for_speech(text)


def get_tts_queue() -> TTSQueue:
    global _tts_queue
    if _tts_queue is None:
        def _speak_handler(text: str) -> None:
            from kratos_agent.output.speech_directives import extract_speech_directives

            directive = extract_speech_directives(text)
            if not directive.valid or not directive.speech_text:
                return
            safe_text = sanitize_speech_text(directive.speech_text)
            try:
                from kratos_agent.live import get_live_runtime
                get_live_runtime().speak_marked(safe_text)
            except Exception:
                try:
                    from .native_voice import get_native_voice
                    get_native_voice().speak(safe_text)
                except Exception:
                    pass

        _tts_queue = TTSQueue(speech_func=_speak_handler)
    return _tts_queue
