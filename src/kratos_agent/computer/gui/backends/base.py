"""Abstract base class for GUI automation backends."""
from __future__ import annotations

import abc

from kratos_agent.computer.gui.models import GUIElement
from kratos_agent.computer.state import ActionResult


class GUIBackend(abc.ABC):
    """Abstract interface for platform-specific and protocol-specific GUI backends."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of backend: 'windows_uia', 'linux_atspi', 'playwright', 'vision', 'coordinate'."""

    @property
    @abc.abstractmethod
    def priority(self) -> int:
        """Priority of this backend in the resolution ladder (lower number = higher priority)."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Returns True if the backend is functional on the current system."""

    @abc.abstractmethod
    def dump_tree(
        self,
        app: str | None = None,
        root_window: str | None = None,
        max_depth: int = 8,
        max_nodes: int = 400,
        visible_only: bool = True,
    ) -> list[GUIElement]:
        """Dumps interactive elements from the accessibility tree or DOM."""

    @abc.abstractmethod
    def find_elements(
        self,
        query: str | None = None,
        role: str | None = None,
        app: str | None = None,
        limit: int = 25,
    ) -> list[GUIElement]:
        """Finds elements matching query and/or role."""

    @abc.abstractmethod
    def find_element(
        self,
        query: str | None = None,
        role: str | None = None,
        app: str | None = None,
    ) -> GUIElement | None:
        """Finds the best single element matching the query."""

    @abc.abstractmethod
    def invoke_element(
        self,
        element: GUIElement,
        pattern: str = "Invoke",
        value: str | None = None,
    ) -> ActionResult:
        """Invokes a control natively without moving the mouse."""

    @abc.abstractmethod
    def click_element(
        self,
        element: GUIElement,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        """Activates an element through a native semantic action."""

    @abc.abstractmethod
    def type_element(
        self,
        element: GUIElement,
        text: str,
        clear_first: bool = False,
    ) -> ActionResult:
        """Enters text into an element."""
