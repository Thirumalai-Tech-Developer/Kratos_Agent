"""Perception caching for screenshot frames and element handles.
Budget: O(1) cache lookups, TTL invalidation.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_TTL_MS = 1500

@dataclass
class CachedFrame:
    frame_ref: str
    data: bytes
    timestamp_ms: float

class PerceptionCache:
    def __init__(self, ttl_ms: int = DEFAULT_TTL_MS):
        self.ttl_ms = ttl_ms
        self._last_frame: Optional[CachedFrame] = None
        self._element_handles: Dict[str, Any] = {}
        self._window_refs: Dict[str, Any] = {}

    def get_frame(self) -> Optional[CachedFrame]:
        if not self._last_frame:
            return None
        age_ms = (time.monotonic() - self._last_frame.timestamp_ms) * 1000
        if age_ms > self.ttl_ms:
            self._last_frame = None
            return None
        return self._last_frame

    def set_frame(self, frame_ref: str, data: bytes) -> CachedFrame:
        self._last_frame = CachedFrame(
            frame_ref=frame_ref,
            data=data,
            timestamp_ms=time.monotonic(),
        )
        return self._last_frame

    def get_element(self, ref: str) -> Optional[Any]:
        return self._element_handles.get(ref)

    def store_elements(self, elements: Dict[str, Any]) -> None:
        self._element_handles.update(elements)

    def invalidate(self) -> None:
        self._last_frame = None
        self._element_handles.clear()
        self._window_refs.clear()

perception_cache = PerceptionCache()
