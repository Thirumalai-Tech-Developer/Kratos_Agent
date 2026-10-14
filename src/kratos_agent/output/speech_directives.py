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
    """Keep the visible answer separate from correctly paired speech segments.

    A speech summary is audio metadata, so neither its markers nor its body
    belong in the visible answer. Malformed, nested, or unmatched directives
    fail closed: their marked body stays hidden and none is spoken aloud.
    """
    source = str(text or "")
    speech: list[str] = []
    cursor = 0
    segment_start: int | None = None
    valid = True

    while cursor < len(source):
        next_open = source.find(OPEN, cursor)
        next_close = source.find(CLOSE, cursor)
        positions = [(pos, marker) for pos, marker in ((next_open, OPEN), (next_close, CLOSE)) if pos >= 0]
        if not positions:
            if segment_start is not None:
                valid = False
            break

        pos, marker = min(positions, key=lambda pair: pair[0])
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

    if segment_start is not None:
        valid = False
    display_filter = DirectiveStreamFilter()
    visible = display_filter.push(source) + display_filter.flush()
    # If parsing failed, suppress all speech in the response rather than trying
    # to guess which fragment the model intended to mark.
    if not valid:
        return SpeechDirective(visible, "", False)

    spoken = " ".join(" ".join(part.split()) for part in speech if part.strip())
    spoken = "".join(ch for ch in spoken if ch >= " " or ch in "\t\n")
    spoken = " ".join(spoken.split())[:MAX_SPEECH_CHARS].strip()
    return SpeechDirective(visible, spoken, True)


class DirectiveStreamFilter:
    """Hide speech directives and their bodies across streamed chunk edges."""

    def __init__(self) -> None:
        self._pending = ""
        self._speech_depth = 0

    def push(self, chunk: str) -> str:
        self._pending += str(chunk or "")
        output: list[str] = []
        cursor = 0
        while cursor < len(self._pending):
            if self._pending.startswith(OPEN, cursor):
                cursor += len(OPEN)
                self._speech_depth += 1
                continue
            if self._pending.startswith(CLOSE, cursor):
                cursor += len(CLOSE)
                self._speech_depth = max(0, self._speech_depth - 1)
                continue
            if len(self._pending) - cursor < len(CLOSE) and any(
                marker.startswith(self._pending[cursor:]) for marker in (OPEN, CLOSE)
            ):
                break
            if not self._speech_depth:
                output.append(self._pending[cursor])
            cursor += 1
        self._pending = self._pending[cursor:]
        return "".join(output)

    def flush(self) -> str:
        # Discard a possible partial control token at end-of-stream so it can
        # never leak into the UI as an implementation detail.
        self._pending = ""
        self._speech_depth = 0
        return ""
