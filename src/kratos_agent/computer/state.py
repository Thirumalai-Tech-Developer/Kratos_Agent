"""Unified computer state and action representation models."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ActionResult:
    """Result of an action executed by the computer engine."""
    ok: bool
    action: str
    detail: str = ""
    data: Optional[Dict[str, Any]] = None
    duration_ms: int = 0
    screenshot_ref: Optional[str] = None
    verified: bool = False
    method_used: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "detail": self.detail,
            "data": self.data,
            "duration_ms": self.duration_ms,
            "screenshot_ref": self.screenshot_ref,
            "verified": self.verified,
            "method_used": self.method_used,
        }


@dataclass
class ComputerAction:
    """Unified normalized action format for computer operations."""
    action: str  # click, type, press, hotkey, scroll, drag, launch, close, navigate, read
    target: Optional[Dict[str, Any]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_state: Optional[Dict[str, Any]] = None
    timeout: float = 10.0

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "action": self.action,
            "parameters": self.parameters,
            "timeout": self.timeout,
        }
        if self.target is not None:
            d["target"] = self.target
        if self.expected_state is not None:
            d["expected_state"] = self.expected_state
        return d


@dataclass
class ObservationDiff:
    """Represents differences between two ComputerStates for verification."""
    state_changed: bool
    changes: List[str] = field(default_factory=list)
    active_window_changed: bool = False
    new_windows: List[str] = field(default_factory=list)
    closed_windows: List[str] = field(default_factory=list)
    dialog_appeared: bool = False
    dialog_closed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_changed": self.state_changed,
            "changes": self.changes,
            "active_window_changed": self.active_window_changed,
            "new_windows": self.new_windows,
            "closed_windows": self.closed_windows,
            "dialog_appeared": self.dialog_appeared,
            "dialog_closed": self.dialog_closed,
            "details": self.details,
        }


@dataclass
class ComputerState:
    """Unified representation of the computer environment."""
    platform: str
    desktop: Optional[str] = None
    active_window: Optional[Dict[str, Any]] = None
    windows: List[Dict[str, Any]] = field(default_factory=list)
    applications: List[Dict[str, Any]] = field(default_factory=list)
    focused_element: Optional[Dict[str, Any]] = None
    clipboard: Optional[str] = None
    screen_size: Optional[Tuple[int, int]] = None
    browser_state: Optional[Dict[str, Any]] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    interactive_elements: List[Dict[str, Any]] = field(default_factory=list)
    generation: int = 1
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "desktop": self.desktop,
            "active_window": self.active_window,
            "windows": self.windows,
            "applications": self.applications,
            "focused_element": self.focused_element,
            "clipboard": self.clipboard[:200] if self.clipboard else None,
            "screen_size": self.screen_size,
            "browser_state": self.browser_state,
            "capabilities": self.capabilities,
            "interactive_elements_count": len(self.interactive_elements),
            "generation": self.generation,
            "timestamp": round(self.timestamp, 3),
        }

    def compact_summary(self) -> str:
        """Compact summary string for token-efficient LLM prompting."""
        active_title = (self.active_window or {}).get("title", "None")
        win_count = len(self.windows)
        app_count = len(self.applications)
        elem_count = len(self.interactive_elements)
        browser = "Connected" if (self.browser_state or {}).get("connected") else "Inactive"
        return (
            f"[ComputerState gen={self.generation} os={self.platform}]\n"
            f"Active Window: {active_title}\n"
            f"Windows: {win_count} open | Apps: {app_count} running | Browser: {browser}\n"
            f"Interactive Controls: {elem_count} detected"
        )
