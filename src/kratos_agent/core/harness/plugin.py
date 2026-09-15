"""DeepSeek Harness - Plugin abstraction and lifecycle management."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from .kernel import HarnessKernel

logger = logging.getLogger(__name__)


class PluginState(str, Enum):
    UNLOADED = "unloaded"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginMetadata:
    """Metadata describing a Harness plugin."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "Kratos Agent"
    category: str = "general"  # model, tool, memory, audit, preset, creator, general
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class HarnessPlugin:
    """Base class for all DeepSeek Harness plugins following the Cordis paradigm."""

    metadata: PluginMetadata

    def __init__(self, metadata: Optional[PluginMetadata] = None, config: Optional[Dict[str, Any]] = None):
        if metadata is not None:
            self.metadata = metadata
        elif not hasattr(self, "metadata"):
            self.metadata = PluginMetadata(
                name=self.__class__.__name__.lower().replace("plugin", ""),
                description=self.__doc__ or "Harness plugin",
            )

        self.name: str = self.metadata.name
        self.config: Dict[str, Any] = config or {}
        self.kernel: Optional["HarnessKernel"] = None
        self.state: PluginState = PluginState.UNLOADED
        self.error_message: Optional[str] = None
        self._disposables: List[Callable[[], Any]] = []

    def on_load(self, kernel: "HarnessKernel") -> None:
        """Called when plugin is attached to the kernel context."""
        self.kernel = kernel
        self.state = PluginState.LOADED
        logger.debug(f"[Harness] Plugin '{self.name}' loaded.")

    def on_enable(self) -> None:
        """Called when plugin transitions to active state."""
        self.state = PluginState.ENABLED
        logger.debug(f"[Harness] Plugin '{self.name}' enabled.")

    def on_disable(self) -> None:
        """Called when plugin is deactivated."""
        self._dispose_all()
        self.state = PluginState.DISABLED
        logger.debug(f"[Harness] Plugin '{self.name}' disabled.")

    def on_unload(self) -> None:
        """Called when plugin is completely removed from the kernel."""
        if self.state == PluginState.ENABLED:
            self.on_disable()
        self.kernel = None
        self.state = PluginState.UNLOADED
        logger.debug(f"[Harness] Plugin '{self.name}' unloaded.")

    def apply_preset(self, preset_name: str, config: Dict[str, Any]) -> None:
        """Reconfigure plugin based on active preset (standard, code, minimal, creator)."""
        self.config.update(config)

    def register_disposable(self, disposable: Callable[[], Any]) -> None:
        """Track a cleanup function to be called on disable/unload."""
        self._disposables.append(disposable)

    def _dispose_all(self) -> None:
        """Execute and clear all cleanup handlers."""
        for disposable in reversed(self._disposables):
            try:
                disposable()
            except Exception as e:
                logger.warning(f"[Harness] Error disposing resource in plugin '{self.name}': {e}")
        self._disposables.clear()

    def get_status(self) -> Dict[str, Any]:
        """Return runtime status of the plugin."""
        return {
            "name": self.name,
            "version": self.metadata.version,
            "category": self.metadata.category,
            "description": self.metadata.description,
            "state": self.state.value,
            "dependencies": self.metadata.dependencies,
            "error": self.error_message,
        }
