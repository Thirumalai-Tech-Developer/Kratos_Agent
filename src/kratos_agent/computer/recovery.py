"""Multi-tier recovery engine for automated fault handling."""
from __future__ import annotations
import time
from typing import Any, Callable, Dict, List, Optional

from kratos_agent.computer.state import ComputerAction, ActionResult
from kratos_agent.computer.gui.errors import FailureType, ComputerError
from kratos_agent.computer.observer import get_observer


class RecoveryEngine:
    """Classifies execution failures and drives multi-tiered recovery.
    
    Recovery ladder:
    Attempt 1: Semantic UI
    Attempt 2: Refresh state
    Attempt 3: Keyboard navigation
    Attempt 4: Application-specific adapter
    Attempt 5: stop with a diagnostic when semantic/keyboard recovery is unavailable
    """

    def classify_failure(self, error: Exception | str) -> FailureType:
        """Determines the failure classification from an error or result detail."""
        if isinstance(error, ComputerError):
            return error.failure_type

        err_str = str(error).lower()
        if "not found" in err_str:
            return FailureType.TARGET_NOT_FOUND
        elif "ambiguous" in err_str:
            return FailureType.AMBIGUOUS_TARGET
        elif "disabled" in err_str:
            return FailureType.ELEMENT_DISABLED
        elif "stale" in err_str:
            return FailureType.STALE_ELEMENT
        elif "permission" in err_str or "access denied" in err_str:
            return FailureType.PERMISSION_DENIED
        elif "timed out" in err_str or "timeout" in err_str:
            return FailureType.TIMEOUT
        elif "verification" in err_str:
            return FailureType.VERIFICATION_FAILED
        return FailureType.UNKNOWN_ERROR

    MAX_RECOVERY_ATTEMPTS: int = 2

    def recover_screen_capture(self) -> bool:
        """Attempts recovery of the screen capture stream (§41)."""
        try:
            from kratos_agent.live.screen import get_screen_stream
            stream = get_screen_stream()
            stream.stop()
            time.sleep(0.2)
            health = stream.start()
            return health.available
        except Exception:
            return False

    def recover_browser_navigation(self, url: str) -> ActionResult:
        """Attempts recovery of browser navigation by refocusing and re-navigating (§41)."""
        from kratos_agent.computer.browser.manager import get_browser_manager
        bm = get_browser_manager()
        existing = bm.find_existing_browser()
        if existing and existing.get("handle"):
            from kratos_agent.computer.apps.focus import focus_window
            from kratos_agent.computer.apps.focus_policy import FocusPolicy
            focus_window(existing["handle"], policy=FocusPolicy.FOCUS_TARGET)
        return bm.open_url(url)

    def recover_browser_focus(self, window_handle: Optional[int] = None) -> bool:
        """Recovers browser window focus and restores if minimized (§41)."""
        from kratos_agent.computer.browser.manager import get_browser_manager
        from kratos_agent.computer.apps.focus import focus_window
        from kratos_agent.computer.apps.focus_policy import FocusPolicy
        bm = get_browser_manager()
        handle = window_handle
        if not handle:
            existing = bm.find_existing_browser()
            handle = existing.get("handle") if existing else None
        if handle:
            return focus_window(handle, policy=FocusPolicy.FORCE_RESTORE)
        return False

    def recover_video_playback(self) -> ActionResult:
        """Attempts to recover paused or stalled video playback (§41)."""
        from kratos_agent.ccs.browser.cdp import cdp_client
        if not cdp_client.is_available():
            return ActionResult(ok=False, action="recover_video", detail="CDP unavailable")
        js_play = """(() => {
            const v = document.querySelector('video');
            if (v) {
                v.muted = false;
                v.play();
                return true;
            }
            return false;
        })()"""
        cdp_client.evaluate(js_play)
        from kratos_agent.computer.browser.playwright import PlaywrightDriver
        drv = PlaywrightDriver()
        v_st = drv.verify_video_playing()
        return ActionResult(
            ok=v_st.is_playing,
            action="recover_video",
            detail=f"Video playback recovery: {'playing' if v_st.is_playing else 'failed'}",
            verified=v_st.is_playing,
        )

    def recover_live_session(self) -> bool:
        """Re-establishes Live session connection (§41)."""
        try:
            from kratos_agent.live import get_live_runtime
            rt = get_live_runtime()
            rt.stop_background()
            time.sleep(0.5)
            rt.start_in_background()
            return True
        except Exception:
            return False

    def execute_with_recovery(
        self,
        action: ComputerAction,
        executor_func: Callable[[ComputerAction, int], ActionResult],
        max_attempts: int = 2,
    ) -> ActionResult:
        """Executes action through bounded recovery (default MAX_RECOVERY_ATTEMPTS = 2) (§42)."""
        last_result: Optional[ActionResult] = None
        bound = min(max_attempts, self.MAX_RECOVERY_ATTEMPTS)

        for attempt in range(1, bound + 1):
            if attempt == 2:
                # Refresh state
                get_observer().observe()
                time.sleep(0.3)

            try:
                result = executor_func(action, attempt)
                if result.ok:
                    return result
                last_result = result
            except Exception as exc:
                ft = self.classify_failure(exc)
                if ft == FailureType.PERMISSION_DENIED:
                    # Do not retry permission-denied errors across other tiers
                    return ActionResult(ok=False, action=action.action, detail=f"Permission denied: {exc}")
                last_result = ActionResult(ok=False, action=action.action, detail=str(exc))

            time.sleep(0.2)

        return last_result or ActionResult(ok=False, action=action.action, detail="All recovery tiers exhausted")



_recovery_engine: Optional[RecoveryEngine] = None


def get_recovery_engine() -> RecoveryEngine:
    global _recovery_engine
    if _recovery_engine is None:
        _recovery_engine = RecoveryEngine()
    return _recovery_engine
