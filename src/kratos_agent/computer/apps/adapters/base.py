"""Base class for application-specific adapters."""
from __future__ import annotations
import abc
from typing import Any, Dict, List, Optional

from kratos_agent.computer.state import ActionResult


class ApplicationAdapter(abc.ABC):
    """Provides high-reliability specialized shortcuts and automation for known applications."""

    @property
    @abc.abstractmethod
    def app_name(self) -> str:
        """Name of the application (e.g. 'chrome', 'vscode', 'notepad')."""
        pass

    @abc.abstractmethod
    def matches(self, window_title: str, process_name: str) -> bool:
        """Returns True if this adapter applies to the given window or process."""
        pass

    @abc.abstractmethod
    def get_shortcuts(self) -> Dict[str, str]:
        """Returns a mapping of action names to keyboard shortcuts."""
        pass
