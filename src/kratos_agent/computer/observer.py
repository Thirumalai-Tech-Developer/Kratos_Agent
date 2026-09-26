"""Computer environment observer and state diff engine."""
from __future__ import annotations

import platform
import time
from typing import Any

from kratos_agent.computer.apps.focus import get_active_window
from kratos_agent.computer.apps.processes import get_process_manager
from kratos_agent.computer.apps.windows import get_window_manager
from kratos_agent.computer.browser.manager import get_browser_manager
from kratos_agent.computer.filesystem.clipboard import get_clipboard_engine
from kratos_agent.computer.state import ComputerState, ObservationDiff
from kratos_agent.computer.state_cache import StateCache, get_state_cache


class ComputerObserver:
    """Continuously observes the computer environment and builds compact states with state caching."""

    def __init__(self) -> None:
        self._generation: int = 1
        self._last_state: ComputerState | None = None
        self._state_cache: StateCache = get_state_cache()

    def observe(
        self,
        include_interactive: bool = True,
        max_elements: int = 150,
        force_refresh: bool = False,
        targeted_query: str | None = None,
    ) -> ComputerState:
        """Captures a complete, compact observation of the computer environment."""
        start = time.time()

        # 1. OS & Window State (fast: ~5ms)
        os_platform = platform.system().lower()
        active_win = get_active_window()
        active_dict = active_win.to_dict() if active_win else None
        all_windows = [w.to_dict() for w in get_window_manager().list_windows()]

        # 2. Browser State (fast: ~2ms)
        browser_st = get_browser_manager().get_state()
        browser_url = browser_st.get("url")

        # 3. Check quick hash against StateCache to eliminate redundant inspections
        active_title = (active_dict or {}).get("title", "")
        quick_hash = self._state_cache.compute_quick_hash(
            active_window_title=active_title,
            window_count=len(all_windows),
            browser_url=browser_url,
        )

        if not force_refresh and not targeted_query and self._state_cache.is_valid(quick_hash):
            cached = self._state_cache.last_state
            if cached is not None:
                self._state_cache.cache_hits += 1
                return cached

        self._generation += 1

        # 4. Running Applications (filtered to GUI apps / processes)
        apps = get_process_manager().list_processes(limit=30)

        # 5. Clipboard (first 200 chars)
        clip_text = get_clipboard_engine().read()

        # 6. Interactive Elements (from A11y or DOM)
        interactive_elements: list[dict[str, Any]] = []
        if include_interactive:
            interactive_elements = self._gather_interactive_elements(
                max_elements=max_elements,
                targeted_query=targeted_query,
            )

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
        self._state_cache.last_state = state
        self._state_cache.last_observation_time = time.time()
        self._state_cache.ui_tree_hash = quick_hash
        self._state_cache.generation = self._generation
        self._state_cache.active_window = active_dict
        self._state_cache.cache_misses += 1
        return state

    def _gather_interactive_elements(
        self,
        max_elements: int = 150,
        targeted_query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Gathers interactive elements from available backends (A11y or DOM)."""
        elements: list[dict[str, Any]] = []

        # Check browser DOM first if active window is a browser
        browser_mgr = get_browser_manager()
        if browser_mgr.is_connected():
            from kratos_agent.computer.gui.backends.playwright import PlaywrightBackend
            pb = PlaywrightBackend()
            if pb.is_available():
                if targeted_query:
                    dom_elems = pb.find_elements(query=targeted_query, limit=max_elements)
                else:
                    dom_elems = pb.dump_tree(max_nodes=max_elements)
                elements.extend([e.to_dict() for e in dom_elems])
                if len(elements) >= max_elements:
                    return elements[:max_elements]

        # Windows UIA
        if platform.system().lower() == "windows":
            from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
            uia = WindowsUIABackend()
            if uia.is_available():
                if targeted_query:
                    uia_elems = uia.find_elements(query=targeted_query, limit=max_elements - len(elements))
                else:
                    uia_elems = uia.dump_tree(max_nodes=max_elements - len(elements))
                elements.extend([e.to_dict() for e in uia_elems])

        return elements[:max_elements]

    def compute_diff(self, before: ComputerState, after: ComputerState) -> ObservationDiff:
        """Compares before and after states to determine if state changed."""
        changes: list[str] = []

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


_observer: ComputerObserver | None = None


def get_observer() -> ComputerObserver:
    global _observer
    if _observer is None:
        _observer = ComputerObserver()
    return _observer
