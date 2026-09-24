"""Abstract base class for GUI automation backends."""
from __future__ import annotations
import abc
from typing import Any, Dict, List, Optional

from kratos_agent.computer.gui.models import GUIElement, Rect, Point
from kratos_agent.computer.state import ActionResult


class GUIBackend(abc.ABC):
    """Abstract interface for platform-specific and protocol-specific GUI backends."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of backend: 'windows_uia', 'linux_atspi', 'playwright', 'vision', 'coordinate'."""
        pass

    @property
    @abc.abstractmethod
    def priority(self) -> int:
        """Priority of this backend in the resolution ladder (lower number = higher priority)."""
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Returns True if the backend is functional on the current system."""
        pass

    @abc.abstractmethod
    def dump_tree(
        self,
        app: Optional[str] = None,
        root_window: Optional[str] = None,
        max_depth: int = 8,
        max_nodes: int = 400,
        visible_only: bool = True,
    ) -> List[GUIElement]:
        """Dumps interactive elements from the accessibility tree or DOM."""
        pass

    @abc.abstractmethod
    def find_elements(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
        limit: int = 25,
    ) -> List[GUIElement]:
        """Finds elements matching query and/or role."""
        pass

    @abc.abstractmethod
    def find_element(
        self,
        query: Optional[str] = None,
        role: Optional[str] = None,
        app: Optional[str] = None,
    ) -> Optional[GUIElement]:
        """Finds the best single element matching the query."""
        pass

    @abc.abstractmethod
    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: Optional[str] = None,
    ) -> ActionResult:
        """Invokes a control natively without moving the mouse."""
        pass

    @abc.abstractmethod
    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        """Activates an element through a native semantic action."""
        pass

    @abc.abstractmethod
    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        """Enters text into an element."""
        pass
