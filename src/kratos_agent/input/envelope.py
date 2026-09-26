from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InputEnvelope:
    request_id: str = field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:10].upper()}")
    session_id: str | None = None
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    text: str = ""
    audio_metadata: dict[str, Any] = field(default_factory=dict)
    image_frames: list[Any] = field(default_factory=list)
    screen_frame: Any = None
    camera_frame: Any = None
    active_window: dict[str, Any] | None = None
    active_browser_tab: dict[str, Any] | None = None
    selected_text: str | None = None
    cursor_context: dict[str, Any] | None = None
    previous_user_turns: list[dict[str, Any]] = field(default_factory=list)
    active_task_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "source": self.source,
            "timestamp": self.timestamp,
            "text": self.text,
            "audio_metadata": self.audio_metadata,
            "image_frames": self.image_frames,
            "screen_frame": self.screen_frame,
            "camera_frame": self.camera_frame,
            "active_window": self.active_window,
            "active_browser_tab": self.active_browser_tab,
            "selected_text": self.selected_text,
            "cursor_context": self.cursor_context,
            "previous_user_turns": self.previous_user_turns,
            "active_task_summary": self.active_task_summary,
        }
