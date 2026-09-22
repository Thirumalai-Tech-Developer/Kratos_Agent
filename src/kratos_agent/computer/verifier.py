"""Action verification engine comparing expected vs actual computer state (§12, §13, §17, §18, §19, §36)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from kratos_agent.computer.state import ComputerState, ObservationDiff, ActionResult
from kratos_agent.computer.observer import get_observer


@dataclass
class ComputerTaskResult:
    """Standardized computer task completion contract (§36)."""
    task_id: str
    success: bool
    verified: bool
    target: Optional[str] = None
    action_count: int = 0
    retries: int = 0
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "verified": self.verified,
            "target": self.target,
            "action_count": self.action_count,
            "retries": self.retries,
            "evidence": self.evidence,
            "error": self.error,
        }


class ActionVerifier:
    """Verifies that an action achieved its expected outcome in the physical computer environment."""

    def verify_browser_url(self, expected_url: str) -> bool:
        """Verifies that active browser URL matches expected URL."""
        from kratos_agent.computer.browser.manager import get_browser_manager
        st = get_browser_manager().get_state()
        actual = (st.get("url") or "").lower()
        return expected_url.lower() in actual

    def verify_browser_title(self, expected_title: str) -> bool:
        """Verifies active browser title contains expected title string."""
        from kratos_agent.computer.browser.manager import get_browser_manager
        st = get_browser_manager().get_state()
        actual = (st.get("title") or "").lower()
        return expected_title.lower() in actual

    def verify_page_loaded(self) -> bool:
        """Verifies that active page is loaded and non-empty."""
        from kratos_agent.computer.browser.manager import get_browser_manager
        bm = get_browser_manager()
        st = bm.get_state()
        if st.get("connected"):
            ready_state = bm.execute_js("document.readyState")
            return ready_state in ("interactive", "complete")
        return bool(st.get("url"))

    def verify_video_present(self) -> bool:
        """Verifies presence of a visible video element on page."""
        from kratos_agent.computer.browser.playwright import PlaywrightDriver
        drv = PlaywrightDriver()
        st = drv.verify_video_playing()
        return st.video_present and st.visible

    def verify_video_playing(self) -> Tuple[bool, Dict[str, Any]]:
        """Verifies progressing video playback using time advancement (§12, §13)."""
        from kratos_agent.computer.browser.playwright import PlaywrightDriver
        drv = PlaywrightDriver()
        v_st = drv.verify_video_playing()
        evidence = {
            "video_present": v_st.video_present,
            "paused": v_st.paused,
            "current_time": v_st.current_time,
            "duration": v_st.duration,
            "visible": v_st.visible,
            "title": v_st.title,
            "url": v_st.url,
        }
        return v_st.is_playing, evidence

    def verify_foreground_window(self, target_handle_or_name: str | int) -> bool:
        """Verifies that target window is actually in the foreground (§6, §7, §19)."""
        from kratos_agent.computer.apps.focus import get_active_window
        active = get_active_window()
        if not active:
            return False
        target_str = str(target_handle_or_name).lower()
        return (
            str(active.id) == target_str
            or target_str in active.title.lower()
            or target_str in active.app_name.lower()
        )

    def verify_action(
        self,
        action: str,
        before_state: ComputerState,
        after_state: ComputerState,
        expected_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Compares before and after states against expected state.
        
        Returns (verified: bool, detail: str).
        """
        diff = get_observer().compute_diff(before_state, after_state)

        # 1. If explicit expected_state criteria provided
        if expected_state:
            # Check window title expectation
            if "window_title" in expected_state:
                expected_title = expected_state["window_title"].lower()
                active_title = (after_state.active_window or {}).get("title", "").lower()
                all_titles = [w.get("title", "").lower() for w in after_state.windows]
                if expected_title not in active_title and not any(expected_title in t for t in all_titles):
                    return False, f"Expected window '{expected_state['window_title']}' not found in active or open windows"

            # Check dialog closed expectation
            if expected_state.get("dialog_closed"):
                if not diff.dialog_closed:
                    return False, "Expected dialog to close, but dialog is still present"

            # Check URL match expectation
            if "url" in expected_state:
                expected_url = expected_state["url"].lower()
                actual_url = ((after_state.browser_state or {}).get("url") or "").lower()
                if expected_url not in actual_url:
                    return False, f"Expected browser URL containing '{expected_state['url']}', got '{actual_url}'"

            # Check video playing expectation (§12, §13)
            if expected_state.get("video_playing"):
                playing, _ = self.verify_video_playing()
                if not playing:
                    return False, "Expected video to be playing with progressing playback time"

            # Check foreground window expectation (§6, §7)
            if "foreground_window" in expected_state:
                target_proc = expected_state["foreground_window"].lower()
                active_proc = ((after_state.active_window or {}).get("title") or "").lower()
                if target_proc not in active_proc:
                    return False, f"Expected foreground window '{target_proc}', got '{active_proc}'"

            # Check process running expectation
            if "process_running" in expected_state:
                target_proc = expected_state["process_running"].lower()
                if not any(target_proc in (p.get("name") or "").lower() for p in after_state.applications):
                    return False, f"Expected process '{target_proc}' to be running"

            # If all explicit criteria passed:
            return True, "All expected state criteria satisfied"

        # 2. General heuristic verification: did the state change as a result of the action?
        if action in ("observe", "inspect", "read", "find", "screenshot"):
            return True, "Observation action verified"

        if diff.state_changed:
            return True, f"State change verified: {'; '.join(diff.changes[:3])}"

        return False, "No observable change in computer state was detected after action execution"


_verifier: Optional[ActionVerifier] = None


def get_verifier() -> ActionVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ActionVerifier()
    return _verifier
