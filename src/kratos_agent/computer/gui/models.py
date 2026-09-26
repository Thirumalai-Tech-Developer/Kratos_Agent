"""Platform-independent GUI element and geometry models."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> Point:
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> Rect:
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            w=data.get("w", data.get("width", 0)),
            h=data.get("h", data.get("height", 0)),
        )


@dataclass
class WindowInfo:
    id: str
    title: str
    app_name: str
    is_active: bool
    bounds: dict[str, int]
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "app_name": self.app_name,
            "is_active": self.is_active,
            "bounds": self.bounds,
            "pid": self.pid,
        }


@dataclass
class DisplayInfo:
    id: str
    is_primary: bool
    bounds: dict[str, int]
    resolution: str
    scale_factor: float = 1.0

    @property
    def width(self) -> int:
        return self.bounds.get("width", 1920)

    @property
    def height(self) -> int:
        return self.bounds.get("height", 1080)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "is_primary": self.is_primary,
            "bounds": self.bounds,
            "resolution": self.resolution,
            "scale_factor": self.scale_factor,
        }


@dataclass
class GUIElement:
    """Platform-independent representation of an interactive or structural GUI element."""
    id: str
    name: str | None = None
    role: str | None = None
    control_type: str | None = None
    text: str | None = None
    value: str | None = None
    description: str | None = None

    enabled: bool = True
    visible: bool = True
    focused: bool = False

    bounds: dict[str, int] | None = None

    parent_id: str | None = None
    backend: str = "unknown"  # windows_uia, linux_atspi, playwright, vision, coordinate

    metadata: dict[str, Any] = field(default_factory=dict)
    generation: int = 1
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0

    @property
    def rect(self) -> Rect | None:
        if not self.bounds:
            return None
        return Rect.from_dict(self.bounds)

    @property
    def center(self) -> Point | None:
        r = self.rect
        return r.center if r else None

    def to_dict(self) -> dict[str, Any]:
        """Compact dictionary format suitable for LLM context or JSON serialization."""
        d: dict[str, Any] = {
            "id": self.id,
            "backend": self.backend,
            "enabled": self.enabled,
            "visible": self.visible,
            "focused": self.focused,
            "generation": self.generation,
            "confidence": round(self.confidence, 2),
        }
        if self.name:
            d["name"] = self.name
        if self.role:
            d["role"] = self.role
        if self.control_type:
            d["control_type"] = self.control_type
        if self.text:
            d["text"] = self.text
        if self.value is not None:
            d["value"] = self.value
        if self.description:
            d["description"] = self.description
        if self.bounds:
            d["bounds"] = self.bounds
        if self.parent_id:
            d["parent_id"] = self.parent_id
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class StaleElementTracker:
    """Tracks generation counter and checks if an element reference is stale."""
    def __init__(self) -> None:
        self._current_generation: int = 1
        self._last_update: float = time.time()

    @property
    def current_generation(self) -> int:
        return self._current_generation

    def advance_generation(self) -> int:
        self._current_generation += 1
        self._last_update = time.time()
        return self._current_generation

    def is_stale(self, element: GUIElement, max_age_seconds: float = 30.0) -> bool:
        """Returns True if the element belongs to an older generation or is timed out."""
        if element.generation > 0 and element.generation < self._current_generation:
            return True
        if (time.time() - element.timestamp) > max_age_seconds:
            return True
        return False

