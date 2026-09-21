"""Configuration for Kratos Gemini Live multimodal integration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _resolve_api_key() -> str:
    """Resolve Gemini API key from environment, .env, or Omni/.env fallback."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key and key.strip():
        return key.strip()

    # Fallback to Omni/.env if present
    omni_env = Path("C:/Users/thiru/Documents/Omni/.env")
    if omni_env.is_file():
        try:
            import dotenv
            omni_vals = dotenv.dotenv_values(str(omni_env))
            omni_key = omni_vals.get("GEMINI_API_KEY") or omni_vals.get("GOOGLE_API_KEY")
            if omni_key and omni_key.strip():
                return omni_key.strip()
        except Exception:
            pass

    return ""


@dataclass
class LiveConfig:
    """Live multimodal configuration settings."""
    api_key: str = field(default_factory=_resolve_api_key)
    model: str = field(
        default_factory=lambda: os.getenv("KRATOS_LIVE_MODEL", "gemini-3.8-live-extended-thinking")
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
    microphone_device: Optional[int | str] = field(
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

    def is_valid(self) -> bool:
        """Check if minimum requirements to connect are met."""
        return bool(self.api_key and self.enabled)
