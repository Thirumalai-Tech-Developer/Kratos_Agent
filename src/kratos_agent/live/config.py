"""Configuration for Kratos Gemini Live multimodal integration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Ensure Google APIs and localhost bypass local system proxies (e.g. tethering/hotspot)
_current_no_proxy = os.getenv("NO_PROXY", "")
_bypass = "googleapis.com,generativelanguage.googleapis.com,127.0.0.1,localhost"
if not _current_no_proxy:
    os.environ["NO_PROXY"] = _bypass
    os.environ["no_proxy"] = _bypass
elif "googleapis.com" not in _current_no_proxy:
    os.environ["NO_PROXY"] = f"{_current_no_proxy},{_bypass}"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]


def _resolve_api_key() -> str:
    """Resolve Gemini credentials from the process environment / project .env only."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return key.strip() if key and key.strip() else ""


@dataclass
class LiveConfig:
    """Live multimodal configuration settings."""
    api_key: str = field(default_factory=_resolve_api_key)
    model: str = field(
        default_factory=lambda: os.getenv("KRATOS_LIVE_MODEL", "gemini-3.8-live")
    )
    voice_name: str = field(
        default_factory=lambda: os.getenv("KRATOS_LIVE_VOICE", "Zephyr")
    )
    video_mode: str = field(
        default_factory=lambda: os.getenv("KRATOS_LIVE_MODE", "camera").lower()
    )
    enabled: bool = field(
        default_factory=lambda: os.getenv("KRATOS_LIVE_ENABLED", "true").lower() not in ("0", "false", "no")
    )
    floating_avatar_enabled: bool = field(
        default_factory=lambda: os.getenv("KRATOS_FLOATING_AVATAR", "true").lower() not in ("0", "false", "no")
    )
    avatar_image_path: str = field(
        default_factory=lambda: os.getenv("KRATOS_AVATAR_IMAGE", "kratos-illu.png")
    )
    avatar_size: int = 110

    # Audio stream settings
    microphone_device: int | str | None = field(
        default_factory=lambda: os.getenv("KRATOS_MIC_DEVICE")
    )
    send_sample_rate: int = 16000
    receive_sample_rate: int = 24000
    channels: int = 1
    chunk_size: int = 1024
    vad_threshold: int = field(
        default_factory=lambda: int(os.getenv("KRATOS_VAD_THRESHOLD", "80"))
    )
    vad_silence_seconds: float = field(
        default_factory=lambda: float(os.getenv("KRATOS_VAD_SILENCE_SECONDS", "1.2"))
    )

    # Video stream settings
    video_fps: float = 1.0
    camera_max_size: tuple[int, int] = (1024, 1024)
    screen_max_size: tuple[int, int] = (1920, 1080)
    camera_jpeg_quality: int = 85
    screen_jpeg_quality: int = 80

    # Thinking & context settings
    thinking_level: str = "LOW"
    context_trigger_tokens: int = 104857
    context_target_tokens: int = 52428

    backend: str = "gemini"

    def is_valid(self) -> bool:
        """Check if minimum requirements to run multimodal layer are met."""
        if not self.enabled:
            return False
        if self.backend == "native":
            return True
        return bool(self.api_key)

    @property
    def is_gemini_backend(self) -> bool:
        if os.getenv("KRATOS_DISABLE_GEMINI_LIVE", "false").lower() in ("true", "1", "yes"):
            return False
        if os.getenv("KRATOS_LIVE_BACKEND", "").lower() == "native":
            return False
        return self.backend in ("gemini", "gemini_live") and bool(self.api_key)
