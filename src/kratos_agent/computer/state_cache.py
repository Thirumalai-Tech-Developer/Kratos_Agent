"""State-aware observation cache with UI hashing and incremental diffs."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from kratos_agent.computer.state import ComputerState


class StateCache:
    """Maintains state awareness and eliminates redundant 5+ second UI inspections.
    
    If the environment (active window, open windows, browser URL) has not changed,
    the previous observation is reused immediately without re-dumping the UIA tree.
    """

    def __init__(self, ttl_seconds: float = 5.0) -> None:
        self.ttl_seconds = ttl_seconds
        self.last_state: ComputerState | None = None
        self.last_observation_time: float = 0.0
        self.generation: int = 1
        self.active_window: dict[str, Any] | None = None
        self.focused_element: dict[str, Any] | None = None
        self.ui_tree_hash: str = ""
        self.browser_state_hash: str = ""
        self.cache_hits: int = 0
        self.cache_misses: int = 0

    def compute_quick_hash(self, active_window_title: str, window_count: int, browser_url: str | None) -> str:
        """Computes a sub-millisecond hash of top-level window and browser state."""
        raw = f"{active_window_title}|{window_count}|{browser_url or ''}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def is_valid(self, quick_hash: str) -> bool:
        """Checks if cached state is still valid and unchanged."""
        if not self.last_state:
            return False
        # If cache expired by TTL, require re-check
        if (time.time() - self.last_observation_time) > self.ttl_seconds:
            return False
        # If top-level state changed, invalidate
        if quick_hash != self.ui_tree_hash:
            return False
        return True

    def get_or_observe(
        self,
        observe_func: Any,
        quick_hash: str,
        force_refresh: bool = False,
    ) -> tuple[ComputerState, bool]:
        """Returns (cached_state, was_cache_hit)."""
        if not force_refresh and self.is_valid(quick_hash):
            self.cache_hits += 1
            return self.last_state, True

        self.cache_misses += 1
        new_state = observe_func()
        self.last_state = new_state
        self.last_observation_time = time.time()
        self.ui_tree_hash = quick_hash
        self.generation = new_state.generation
        self.active_window = new_state.active_window
        return new_state, False

    def invalidate(self) -> None:
        """Explicitly invalidates the cache after mutating actions (click, type, launch)."""
        self.ui_tree_hash = ""
        self.last_observation_time = 0.0


_state_cache: StateCache | None = None


def get_state_cache() -> StateCache:
    global _state_cache
    if _state_cache is None:
        _state_cache = StateCache()
    return _state_cache
