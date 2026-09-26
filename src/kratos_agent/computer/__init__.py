"""Kratos Universal Computer-Use Engine."""
from __future__ import annotations

from kratos_agent.computer.capabilities import probe_capabilities
from kratos_agent.computer.executor import ActionExecutor, get_executor
from kratos_agent.computer.gui.models import GUIElement, Point, Rect
from kratos_agent.computer.manager import ComputerManager, get_computer_manager
from kratos_agent.computer.observer import ComputerObserver, get_observer
from kratos_agent.computer.recovery import RecoveryEngine, get_recovery_engine
from kratos_agent.computer.state import (
    ActionResult,
    ComputerAction,
    ComputerState,
    ObservationDiff,
)
from kratos_agent.computer.verifier import ActionVerifier, get_verifier

__all__ = [
    "ActionExecutor",
    "ActionResult",
    "ActionVerifier",
    "ComputerAction",
    "ComputerManager",
    "ComputerObserver",
    "ComputerState",
    "GUIElement",
    "ObservationDiff",
    "Point",
    "RecoveryEngine",
    "Rect",
    "get_computer_manager",
    "get_executor",
    "get_observer",
    "get_recovery_engine",
    "get_verifier",
    "probe_capabilities",
]
