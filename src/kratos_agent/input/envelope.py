from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class InputEnvelope:
    request_id: str = field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:10].upper()}")
    session_id: Optional[str] = None
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    text: str = ""
    audio_metadata: Dict[str, Any] = field(default_factory=dict)
    image_frames: List[Any] = field(default_factory=list)
    screen_frame: Any = None
    camera_frame: Any = None
    active_window: Optional[Dict[str, Any]] = None
    active_browser_tab: Optional[Dict[str, Any]] = None
    selected_text: Optional[str] = None
    cursor_context: Optional[Dict[str, Any]] = None
    previous_user_turns: List[Dict[str, Any]] = field(default_factory=list)
    active_task_summary: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
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
