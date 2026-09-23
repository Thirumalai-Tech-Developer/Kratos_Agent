"""Browser task state machine, action idempotency, and retry budgets."""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Dict, Optional, Set


class BrowserTaskState(str, Enum):
    BROWSER_ATTACHING = "browser_attaching"
    RESOLVING_TARGET = "resolving_target"
    WINDOW_READY = "window_ready"
    TARGET_READY = "target_ready"
    TAB_READY = "tab_ready"
    NAVIGATING = "navigating"
    PAGE_LOADING = "page_loading"
    PAGE_READY = "page_ready"
    SEARCHING = "searching"
    RESULT_SELECTED = "result_selected"
    PLAY_REQUESTED = "play_requested"
    ACTION_EXECUTING = "action_executing"
    ACTION_VERIFICATION = "action_verification"
    VERIFYING = "verifying"
    TASK_FINAL_VERIFICATION = "task_final_verification"
    COMPLETED = "completed"
    FAILED = "failed"


class BrowserActionRegistry:
    """Tracks executed actions by idempotency key to prevent duplicate execution loops (§14, §15, §16)."""

    MAX_PLAY_RETRIES: int = 2

    def __init__(self) -> None:
        self._successful_actions: Set[str] = set()
        self._action_attempts: Dict[str, int] = {}

    @staticmethod
    def compute_action_key(
        task_id: str,
        target_page_id: Optional[str],
        action_type: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Computes a deterministic hash for an action execution."""
        args_str = json.dumps(arguments or {}, sort_keys=True)
        raw = f"{task_id}::{target_page_id or 'default'}::{action_type}::{args_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def was_successful(self, action_key: str) -> bool:
        return action_key in self._successful_actions

    def record_success(self, action_key: str) -> None:
        self._successful_actions.add(action_key)

    def record_attempt(self, action_key: str) -> int:
        count = self._action_attempts.get(action_key, 0) + 1
        self._action_attempts[action_key] = count
        return count

    def can_retry(self, action_key: str, max_retries: int = MAX_PLAY_RETRIES) -> bool:
        return self._action_attempts.get(action_key, 0) < max_retries

    def clear(self) -> None:
        self._successful_actions.clear()
        self._action_attempts.clear()


_action_registry: Optional[BrowserActionRegistry] = None


def get_browser_action_registry() -> BrowserActionRegistry:
    global _action_registry
    if _action_registry is None:
        _action_registry = BrowserActionRegistry()
    return _action_registry
