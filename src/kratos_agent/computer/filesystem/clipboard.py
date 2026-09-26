"""Cross-application clipboard engine."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from kratos_agent.computer.state import ActionResult

try:
    import pyperclip
except ImportError:
    pyperclip = None


class ClipboardEngine:
    """Manages the system clipboard for high-speed cross-application text transfer."""

    def read(self) -> str:
        """Reads current text from the clipboard."""
        if pyperclip:
            try:
                return pyperclip.paste()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
        return ""

    def write(self, text: str) -> ActionResult:
        """Copies text to the clipboard."""
        if pyperclip:
            try:
                pyperclip.copy(text)
                return ActionResult(ok=True, action="clipboard_write", detail=f"Copied {len(text)} chars to clipboard")
            except Exception as e:
                return ActionResult(ok=False, action="clipboard_write", detail=str(e))
        return ActionResult(ok=False, action="clipboard_write", detail="pyperclip not available")

    def clear(self) -> ActionResult:
        """Clears the clipboard."""
        return self.write("")


_clipboard_engine: ClipboardEngine | None = None


def get_clipboard_engine() -> ClipboardEngine:
    global _clipboard_engine
    if _clipboard_engine is None:
        _clipboard_engine = ClipboardEngine()
    return _clipboard_engine
