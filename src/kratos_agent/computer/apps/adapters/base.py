"""Base class for application-specific adapters."""
from __future__ import annotations

import abc


class ApplicationAdapter(abc.ABC):
    """Provides high-reliability specialized shortcuts and automation for known applications."""

    @property
    @abc.abstractmethod
    def app_name(self) -> str:
        """Name of the application (e.g. 'chrome', 'vscode', 'notepad')."""

    @abc.abstractmethod
    def matches(self, window_title: str, process_name: str) -> bool:
        """Returns True if this adapter applies to the given window or process."""

    @abc.abstractmethod
    def get_shortcuts(self) -> dict[str, str]:
        """Returns a mapping of action names to keyboard shortcuts."""
