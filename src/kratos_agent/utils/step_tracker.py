"""Step tracker — legacy compatibility stub.

In the enhanced Kratos architecture, all live rendering is driven by the central
EventBus and KratosLiveRenderer rather than uncontrolled background threads printing
directly to sys.stdout.
"""
from __future__ import annotations

from typing import Optional


class SingleLineStepTracker:
    def __init__(self) -> None:
        self._active_text: Optional[str] = None
        self._running: bool = False
        self.enabled: bool = False  # Disabled by default so Rich Live renderer owns stdout

    def start(self, text: str) -> None:
        self._active_text = text
        self._running = True

    def update(self, text: str) -> None:
        self._active_text = text

    def stop_spinner(self) -> None:
        self._running = False

    def complete(self, title: str, detail: str = "", success: bool = True) -> None:
        self._running = False

    def fail(self, title: str, error: str = "") -> None:
        self._running = False


step_tracker = SingleLineStepTracker()
