"""Computer environment observer and state diff engine."""
from __future__ import annotations
import platform
import time
from typing import Any, Dict, List, Optional, Tuple

from kratos_agent.computer.state import ComputerState, ObservationDiff
from kratos_agent.computer.gui.models import GUIElement, WindowInfo
from kratos_agent.computer.apps.windows import get_window_manager
from kratos_agent.computer.apps.focus import get_active_window
from kratos_agent.computer.apps.processes import get_process_manager
from kratos_agent.computer.filesystem.clipboard import get_clipboard_engine
from kratos_agent.computer.browser.manager import get_browser_manager


class ComputerObserver:
    """Continuously observes the computer environment and builds compact states."""

    def __init__(self) -> None:
        self._generation: int = 1
        self._last_state: Optional[ComputerState] = None

    def observe(
        self,
        include_interactive: bool = True,
        max_elements: int = 150,
    ) -> ComputerState:
        """Captures a complete, compact observation of the computer environment."""
        start = time.time()
        self._generation += 1

        # 1. OS & Window State
        os_platform = platform.system().lower()
        active_win = get_active_window()
        active_dict = active_win.to_dict() if active_win else None
        all_windows = [w.to_dict() for w in get_window_manager().list_windows()]

        # 2. Running Applications (filtered to GUI apps / processes)
        apps = get_process_manager().list_processes(limit=30)

        # 3. Clipboard (first 200 chars)
        clip_text = get_clipboard_engine().read()

        # 4. Browser State
        browser_st = get_browser_manager().get_state()

        # 5. Interactive Elements (from A11y or DOM)
        interactive_elements: List[Dict[str, Any]] = []
        if include_interactive:
            interactive_elements = self._gather_interactive_elements(max_elements=max_elements)

        state = ComputerState(
            platform=os_platform,
            desktop="main",
            active_window=active_dict,
            windows=all_windows,
            applications=apps,
            focused_element=None,
            clipboard=clip_text,
            screen_size=(1920, 1080),
            browser_state=browser_st,
            capabilities={"gui": True, "browser": browser_st.get("connected", False)},
            interactive_elements=interactive_elements,
            generation=self._generation,
            timestamp=start,
        )
        self._last_state = state
        return state

    def _gather_interactive_elements(self, max_elements: int = 150) -> List[Dict[str, Any]]:
        """Gathers interactive elements from available backends (A11y or DOM)."""
        elements: List[Dict[str, Any]] = []

        # Check browser DOM first if active window is a browser
        browser_mgr = get_browser_manager()
        if browser_mgr.is_connected():
            from kratos_agent.computer.gui.backends.playwright import PlaywrightBackend
            pb = PlaywrightBackend()
            if pb.is_available():
                dom_elems = pb.dump_tree(max_nodes=max_elements)
                elements.extend([e.to_dict() for e in dom_elems])
                if len(elements) >= max_elements:
                    return elements[:max_elements]

        # Windows UIA
        if platform.system().lower() == "windows":
            from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
            uia = WindowsUIABackend()
            if uia.is_available():
                uia_elems = uia.dump_tree(max_nodes=max_elements - len(elements))
                elements.extend([e.to_dict() for e in uia_elems])

        return elements[:max_elements]

    def compute_diff(self, before: ComputerState, after: ComputerState) -> ObservationDiff:
        """Compares before and after states to determine if state changed."""
        changes: List[str] = []

        # 1. Active window changed?
        before_active = (before.active_window or {}).get("title", "")
        after_active = (after.active_window or {}).get("title", "")
        active_changed = (before_active != after_active)
        if active_changed:
            changes.append(f"Active window changed: '{before_active}' -> '{after_active}'")

        # 2. Windows opened/closed
        before_win_titles = {w.get("title", "") for w in before.windows}
        after_win_titles = {w.get("title", "") for w in after.windows}

        new_wins = list(after_win_titles - before_win_titles)
        closed_wins = list(before_win_titles - after_win_titles)

        if new_wins:
            changes.append(f"New windows opened: {new_wins}")
        if closed_wins:
            changes.append(f"Windows closed: {closed_wins}")

        # 3. Dialog checks
        dialog_keywords = ("dialog", "alert", "save as", "open file", "confirm", "warning", "error")
        dialog_appeared = any(any(dk in t.lower() for dk in dialog_keywords) for t in new_wins)
        dialog_closed = any(any(dk in t.lower() for dk in dialog_keywords) for t in closed_wins)

        # 4. Browser URL / title changed
        before_url = (before.browser_state or {}).get("url")
        after_url = (after.browser_state or {}).get("url")
        if before_url != after_url:
            changes.append(f"Browser URL changed: '{before_url}' -> '{after_url}'")

        # 5. Clipboard changed
        if before.clipboard != after.clipboard:
            changes.append("Clipboard content updated")

        state_changed = bool(changes) or active_changed or bool(new_wins) or bool(closed_wins)

        return ObservationDiff(
            state_changed=state_changed,
            changes=changes,
            active_window_changed=active_changed,
            new_windows=new_wins,
            closed_windows=closed_wins,
            dialog_appeared=dialog_appeared,
            dialog_closed=dialog_closed,
        )


_observer: Optional[ComputerObserver] = None


def get_observer() -> ComputerObserver:
    global _observer
    if _observer is None:
        _observer = ComputerObserver()
    return _observer
