"""Live event contracts and status tracking for Kratos Multimodal Live."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


from enum import Enum


class LiveState(str, Enum):
    """Explicit Gemini Live connection and interaction state machine (§14, §15)."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    STOPPING = "stopping"
    # Interaction sub-states
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    ERROR = "error"
    IDLE = "idle"


class ComponentHealth(str, Enum):
    """Real component health state distinguishing configured vs verified operational (§8)."""
    OFFLINE = "offline"
    STARTING = "starting"
    ONLINE = "online"
    MUTED = "muted"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass
class LiveStatus:
    """Central status of the Live multimodal subsystem (§13, §14, §15)."""
    gemini_connected: bool = False
    microphone_active: bool = False
    speaker_active: bool = False
    camera_active: bool = False
    screen_active: bool = False
    active_task_id: Optional[str] = None
    active_session_id: Optional[str] = None
    muted: bool = False
    video_mode: str = "camera"
    current_state: LiveState = LiveState.DISCONNECTED
    last_transcript: str = ""
    last_error: Optional[str] = None
    microphone_health: str = "offline"
    screen_health: str = "offline"
    camera_health: str = "offline"
    speaker_health: str = "offline"
    live_health: str = "disconnected"
    last_heartbeat: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gemini_connected": self.gemini_connected,
            "microphone_active": self.microphone_active,
            "speaker_active": self.speaker_active,
            "camera_active": self.camera_active,
            "screen_active": self.screen_active,
            "active_task_id": self.active_task_id,
            "active_session_id": self.active_session_id,
            "muted": self.muted,
            "video_mode": self.video_mode,
            "current_state": self.current_state.value if isinstance(self.current_state, LiveState) else str(self.current_state),
            "last_transcript": self.last_transcript,
            "last_error": self.last_error,
            "microphone_health": self.microphone_health,
            "screen_health": self.screen_health,
            "camera_health": self.camera_health,
            "speaker_health": self.speaker_health,
            "live_health": self.live_health,
            "last_heartbeat": self.last_heartbeat,
            "updated_at": self.updated_at,
        }



StatusListener = Callable[[LiveStatus], None]


class LiveStatusHub:
    """Publishes Live status updates to registered listeners (CLI, Web, SSE)."""

    def __init__(self, initial_status: Optional[LiveStatus] = None) -> None:
        self.status = initial_status or LiveStatus()
        self._listeners: List[StatusListener] = []

    def subscribe(self, listener: StatusListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: StatusListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def update(self, **kwargs: Any) -> LiveStatus:
        for k, v in kwargs.items():
            if hasattr(self.status, k):
                setattr(self.status, k, v)
        self.status.updated_at = time.time()
        for listener in list(self._listeners):
            try:
                listener(self.status)
            except Exception:
                pass
        return self.status

    def get_status(self) -> LiveStatus:
        return self.status
