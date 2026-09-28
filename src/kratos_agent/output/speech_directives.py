"""Explicit, fail-closed directives for text that may be spoken aloud."""
from __future__ import annotations

from dataclasses import dataclass


OPEN = "[[speak]]"
CLOSE = "[[/speak]]"
MAX_SPEECH_CHARS = 240


@dataclass(frozen=True, slots=True)
class SpeechDirective:
    display_text: str
    speech_text: str
    valid: bool


def extract_speech_directives(text: str) -> SpeechDirective:
    """Remove directive tags and collect only correctly paired speak segments.

    Malformed, nested, or unmatched directives fail closed: their text remains
    visible, but none of it is sent to a speech backend.
    """
    source = str(text or "")
    display: list[str] = []
    speech: list[str] = []
    cursor = 0
    segment_start: int | None = None
    valid = True

    while cursor < len(source):
        next_open = source.find(OPEN, cursor)
        next_close = source.find(CLOSE, cursor)
        positions = [(pos, marker) for pos, marker in ((next_open, OPEN), (next_close, CLOSE)) if pos >= 0]
        if not positions:
            display.append(source[cursor:])
            if segment_start is not None:
                valid = False
            break

        pos, marker = min(positions, key=lambda pair: pair[0])
        display.append(source[cursor:pos])
        if marker == OPEN:
            if segment_start is not None:
                valid = False
            else:
                segment_start = pos + len(OPEN)
        else:
            if segment_start is None:
                valid = False
            else:
                speech.append(source[segment_start:pos])
                segment_start = None
        cursor = pos + len(marker)

    visible = "".join(display)
    # If parsing failed, suppress all speech in the response rather than trying
    # to guess which fragment the model intended to mark.
    if not valid:
        return SpeechDirective(visible, "", False)

    spoken = " ".join(" ".join(part.split()) for part in speech if part.strip())
    spoken = "".join(ch for ch in spoken if ch >= " " or ch in "\t\n")
    spoken = " ".join(spoken.split())[:MAX_SPEECH_CHARS].strip()
    return SpeechDirective(visible, spoken, True)


class DirectiveStreamFilter:
    """Strip directive markers from streamed display text across chunk edges."""

    def __init__(self) -> None:
        self._pending = ""

    def push(self, chunk: str) -> str:
        self._pending += str(chunk or "")
        output: list[str] = []
        while self._pending:
            if self._pending.startswith(OPEN):
                self._pending = self._pending[len(OPEN):]
                continue
            if self._pending.startswith(CLOSE):
                self._pending = self._pending[len(CLOSE):]
                continue
            if any(marker.startswith(self._pending) for marker in (OPEN, CLOSE)):
                break
            output.append(self._pending[0])
            self._pending = self._pending[1:]
        return "".join(output)

    def flush(self) -> str:
        # Discard a possible partial control token at end-of-stream so it can
        # never leak into the UI as an implementation detail.
        self._pending = ""
        return ""
