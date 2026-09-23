from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ScreenObservation:
    frame_id: str
    timestamp: float
    width: int
    height: int
    active_window: Any = None
    active_application: Any = None
    active_browser_tab: Any = None
    image: Any = None


def capture_screen() -> ScreenObservation:
    from kratos_agent.live.screen import get_screen_stream
    frame = get_screen_stream().capture_now()
    if frame is None:
        raise RuntimeError("Screen capture returned no frame.")
    return ScreenObservation(
        frame_id=getattr(frame, "frame_id", f"frame-{int(time.time()*1000)}"),
        timestamp=time.time(),
        width=getattr(frame, "width", 0),
        height=getattr(frame, "height", 0),
        image=frame,
    )
