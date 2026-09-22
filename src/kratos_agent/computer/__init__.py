"""Kratos Universal Computer-Use Engine."""
from __future__ import annotations

from kratos_agent.computer.state import ComputerState, ComputerAction, ActionResult, ObservationDiff
from kratos_agent.computer.manager import ComputerManager, get_computer_manager
from kratos_agent.computer.gui.models import GUIElement, Rect, Point
from kratos_agent.computer.observer import ComputerObserver, get_observer
from kratos_agent.computer.executor import ActionExecutor, get_executor
from kratos_agent.computer.verifier import ActionVerifier, get_verifier
from kratos_agent.computer.recovery import RecoveryEngine, get_recovery_engine
from kratos_agent.computer.capabilities import probe_capabilities

__all__ = [
    "ComputerState",
    "ComputerAction",
    "ActionResult",
    "ObservationDiff",
    "ComputerManager",
    "get_computer_manager",
    "GUIElement",
    "Rect",
    "Point",
    "ComputerObserver",
    "get_observer",
    "ActionExecutor",
    "get_executor",
    "ActionVerifier",
    "get_verifier",
    "RecoveryEngine",
    "get_recovery_engine",
    "probe_capabilities",
]
