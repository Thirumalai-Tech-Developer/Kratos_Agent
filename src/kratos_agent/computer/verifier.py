"""Action verification engine comparing expected vs actual computer state."""
from __future__ import annotations
import time
from typing import Any, Dict, Optional

from kratos_agent.computer.state import ComputerState, ObservationDiff, ActionResult
from kratos_agent.computer.observer import get_observer


class ActionVerifier:
    """Verifies that an action achieved its expected outcome in the physical computer environment."""

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

            # Check process running expectation
            if "process_running" in expected_state:
                target_proc = expected_state["process_running"].lower()
                if not any(target_proc in (p.get("name") or "").lower() for p in after_state.applications):
                    return False, f"Expected process '{target_proc}' to be running"

            # If all explicit criteria passed:
            return True, "All expected state criteria satisfied"

        # 2. General heuristic verification: did the state change as a result of the action?
        # Non-mutating actions (e.g. read, observe, inspect) do not require state changes
        if action in ("observe", "inspect", "read", "find", "screenshot"):
            return True, "Observation action verified"

        # Mutating actions (click, type, launch, close, navigate) should typically produce state diff
        if diff.state_changed:
            return True, f"State change verified: {'; '.join(diff.changes[:3])}"

        return False, "No observable change in computer state was detected after action execution"


_verifier: Optional[ActionVerifier] = None


def get_verifier() -> ActionVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ActionVerifier()
    return _verifier
