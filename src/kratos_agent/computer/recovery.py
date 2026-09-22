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
    Attempt 5: Vision grounding
    Attempt 6: Coordinate fallback
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

    def execute_with_recovery(
        self,
        action: ComputerAction,
        executor_func: Callable[[ComputerAction, int], ActionResult],
        max_attempts: int = 6,
    ) -> ActionResult:
        """Executes action through the recovery ladder."""
        last_result: Optional[ActionResult] = None

        for attempt in range(1, max_attempts + 1):
            # Attempt tiers:
            # 1 = Semantic UI
            # 2 = Refresh state & retry
            # 3 = Keyboard
            # 4 = Application adapter
            # 5 = Vision
            # 6 = Coordinate fallback
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
