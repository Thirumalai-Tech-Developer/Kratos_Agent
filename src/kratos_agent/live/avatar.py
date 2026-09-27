"""OpenPets-inspired Windows floating desktop AI assistant avatar for Kratos.

Renders an interactive animated AI pet companion (Cyber Kitty, Cyber Bot, Shiba Inu, Baby Drake)
floating on the Windows desktop with:
- Hover action bar revealing:
  1. 💬 Chat: Direct interactive chat balloon attached to pet
  2. 🎙️ Mic: Toggle live voice / microphone mute
  3. 👁️ Vision: Trigger screen context inspection
  4. ⋯ More: 3-dots context menu for pet selection, edge docking, web console
- Expressive animations: idle breathing, eye blinking, ear wiggles, mouth speech waves,
  joyful petting reaction with heart particles (`❤️ ✨`), and comic speech/thought bubbles.
"""
from __future__ import annotations

import logging
import math
import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw, ImageTk

from .events import LiveState, LiveStatus, LiveStatusHub

logger = logging.getLogger(__name__)

TRANSPARENT_COLOR = "#010101"

# State color palette for collar / visor / halos
STATE_COLORS: dict[LiveState, str] = {
    LiveState.DISCONNECTED: "#64748B",   # Slate gray
    LiveState.CONNECTING: "#F59E0B",     # Amber pulse
    LiveState.CONNECTED: "#06B6D4",      # Cyan steady
    LiveState.DEGRADED: "#F97316",       # Coral orange warning
    LiveState.RECONNECTING: "#EA580C",   # Dark orange warning
    LiveState.FAILED: "#EF4444",         # Red error
    LiveState.STOPPING: "#64748B",       # Muted slate
    LiveState.LISTENING: "#10B981",      # Neon emerald green
    LiveState.THINKING: "#A855F7",       # Purple / violet
    LiveState.EXECUTING: "#6366F1",      # Electric indigo
    LiveState.SPEAKING: "#F97316",       # Fiery coral / orange
    LiveState.ERROR: "#EF4444",          # Crimson red
    LiveState.IDLE: "#3B82F6",           # Calm blue
}

STATE_LABELS: dict[LiveState, str] = {
    LiveState.DISCONNECTED: "Disconnected",
    LiveState.CONNECTING: "Connecting...",
    LiveState.CONNECTED: "Ready",
    LiveState.DEGRADED: "Degraded",
    LiveState.RECONNECTING: "Reconnecting...",
    LiveState.FAILED: "Failed",
    LiveState.STOPPING: "Stopping...",
    LiveState.LISTENING: "Listening...",
    LiveState.THINKING: "Thinking...",
    LiveState.EXECUTING: "Executing...",
    LiveState.SPEAKING: "Speaking...",
    LiveState.ERROR: "Error",
    LiveState.IDLE: "Pet Happy",
}


def _make_circular_avatar(image_path: str, size: int, border_color: str | None = None) -> Image.Image:
    """Loads and crops an image to an antialiased circular avatar on transparent background."""
    if not os.path.exists(image_path):
        im = Image.new("RGBA", (size, size), (30, 41, 59, 255))
        d = ImageDraw.Draw(im)
        d.ellipse((4, 4, size - 4, size - 4), fill=(99, 102, 241, 255))
    else:
        im = Image.open(image_path).convert("RGBA")
        im = im.resize((size, size), Image.Resampling.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    bg = Image.new("RGBA", (size, size), (1, 1, 1, 0))
    bg.paste(im, (0, 0), mask=mask)

    if border_color:
        border_draw = ImageDraw.Draw(bg)
        border_draw.ellipse((1, 1, size - 2, size - 2), outline=border_color, width=2)

    return bg


def render_openpet_frame(
    pet_type: str = "kitty",
    size: int = 120,
    state_color: str = "#06B6D4",
    t: float = 0.0,
    is_blinking: bool = False,
    is_speaking: bool = False,
    is_petting: bool = False,
    custom_image_path: str = "kratos-illu.png",
) -> Image.Image:
    """Renders a procedural antialiased OpenPets sprite with mood expressions."""
    pet_type = pet_type.lower()
    if pet_type == "custom":
        return _make_circular_avatar(custom_image_path, size, border_color=state_color)

    scale = 2
    w, h = size * scale, size * scale
    im = Image.new("RGBA", (w, h), (1, 1, 1, 0))
    draw = ImageDraw.Draw(im)
    cx, cy = w // 2, h // 2 + int(6 * scale)

    # Petting bounce or breathing bob
    bounce_amp = (7 * scale) if is_petting else (2.5 * scale)
    bounce_speed = 8.0 if is_petting else 2.6
    bounce = int(math.sin(t * bounce_speed) * bounce_amp)
    py = cy + bounce

    # Soft contact ground shadow
    sw = int(36 * scale)
    sh = int(8 * scale)
    draw.ellipse((cx - sw, cy + int(42 * scale) - sh, cx + sw, cy + int(42 * scale) + sh), fill=(0, 0, 0, 45))

    if pet_type == "kitty":
        # 🐱 Cyber Kitty
        tail_speed = 6.0 if is_petting else 3.0
        tail_angle = math.sin(t * tail_speed) * 0.4
        tx_base, ty_base = cx + int(22 * scale), py + int(20 * scale)
        tx_mid = tx_base + int(math.cos(tail_angle) * (18 * scale))
        ty_mid = ty_base - int(math.sin(tail_angle + 0.5) * (18 * scale))
        tx_tip = tx_mid + int(math.cos(tail_angle + 0.8) * (16 * scale))
        ty_tip = ty_mid - int(math.sin(tail_angle + 0.8) * (16 * scale))
        draw.line([(tx_base, ty_base), (tx_mid, ty_mid), (tx_tip, ty_tip)], fill="#2E2E3E", width=int(7 * scale))
        draw.ellipse((tx_tip - int(4 * scale), ty_tip - int(4 * scale), tx_tip + int(4 * scale), ty_tip + int(4 * scale)), fill="#2E2E3E")

        # Body & Chest fluff
        bw, bh = int(28 * scale), int(24 * scale)
        draw.ellipse((cx - bw, py + int(8 * scale) - bh, cx + bw, py + int(8 * scale) + bh), fill="#242434", outline="#3E3E54", width=int(2 * scale))
        cw, ch = int(12 * scale), int(14 * scale)
        draw.ellipse((cx - cw, py + int(10 * scale) - ch, cx + cw, py + int(10 * scale) + ch), fill="#E2E8F0")

        # Ears
        ear_twitch = math.sin(t * 3.0) * (3 * scale) if is_petting else (math.sin(t * 1.5) * 3 if (int(t) % 4 == 0) else 0)
        draw.polygon([(cx - int(24 * scale), py - int(10 * scale)), (cx - int(34 * scale) - int(ear_twitch), py - int(40 * scale)), (cx - int(10 * scale), py - int(20 * scale))], fill="#242434", outline="#3E3E54")
        draw.polygon([(cx - int(22 * scale), py - int(12 * scale)), (cx - int(30 * scale) - int(ear_twitch), py - int(34 * scale)), (cx - int(12 * scale), py - int(20 * scale))], fill="#F472B6")
        draw.polygon([(cx + int(10 * scale), py - int(20 * scale)), (cx + int(34 * scale), py - int(40 * scale)), (cx + int(24 * scale), py - int(10 * scale))], fill="#242434", outline="#3E3E54")
        draw.polygon([(cx + int(12 * scale), py - int(20 * scale)), (cx + int(30 * scale), py - int(34 * scale)), (cx + int(22 * scale), py - int(12 * scale))], fill="#F472B6")

        # Head
        hw, hh = int(32 * scale), int(26 * scale)
        draw.ellipse((cx - hw, py - int(5 * scale) - hh, cx + hw, py - int(5 * scale) + hh), fill="#242434", outline="#3E3E54", width=int(2 * scale))

        # Collar & Cyber Gem
        col_y = py + int(12 * scale)
        draw.line([(cx - int(16 * scale), col_y), (cx + int(16 * scale), col_y)], fill="#6366F1", width=int(3.5 * scale))
        gem_r = int(5 * scale)
        draw.ellipse((cx - gem_r, col_y - gem_r // 2, cx + gem_r, col_y + int(gem_r * 1.4)), fill=state_color, outline="#FFFFFF", width=int(1.5 * scale))

        # Cheeks blush
        blush_r = int(6 * scale)
        blush_alpha = 180 if is_petting else 130
        draw.ellipse((cx - int(22 * scale) - blush_r, py - int(2 * scale) - blush_r, cx - int(22 * scale) + blush_r, py - int(2 * scale) + blush_r), fill=(255, 140, 160, blush_alpha))
        draw.ellipse((cx + int(22 * scale) - blush_r, py - int(2 * scale) - blush_r, cx + int(22 * scale) + blush_r, py - int(2 * scale) + blush_r), fill=(255, 140, 160, blush_alpha))

        # Whiskers
        wy = py - int(3 * scale)
        draw.line([(cx - int(18 * scale), wy - int(3 * scale)), (cx - int(36 * scale), wy - int(7 * scale))], fill="#71717A", width=int(1.5 * scale))
        draw.line([(cx - int(18 * scale), wy + int(3 * scale)), (cx - int(36 * scale), wy + int(5 * scale))], fill="#71717A", width=int(1.5 * scale))
        draw.line([(cx + int(18 * scale), wy - int(3 * scale)), (cx + int(36 * scale), wy - int(7 * scale))], fill="#71717A", width=int(1.5 * scale))
        draw.line([(cx + int(18 * scale), wy + int(3 * scale)), (cx + int(36 * scale), wy + int(5 * scale))], fill="#71717A", width=int(1.5 * scale))

        # Eyes
        eye_y = py - int(8 * scale)
        ew, eh = int(6 * scale), int(9 * scale)
        if is_blinking or is_petting:
            draw.arc((cx - int(16 * scale) - ew, eye_y - eh, cx - int(16 * scale) + ew, eye_y + eh), start=30, end=150, fill="#FFFFFF", width=int(3 * scale))
            draw.arc((cx + int(16 * scale) - ew, eye_y - eh, cx + int(16 * scale) + ew, eye_y + eh), start=30, end=150, fill="#FFFFFF", width=int(3 * scale))
        else:
            for ex in (cx - int(16 * scale), cx + int(16 * scale)):
                draw.ellipse((ex - ew, eye_y - eh, ex + ew, eye_y + eh), fill="#0F172A")
                draw.ellipse((ex - ew + 1, eye_y - eh + 2, ex + ew - 1, eye_y + eh - 1), fill=state_color)
                pw, ph = int(3 * scale), int(5 * scale)
                draw.ellipse((ex - pw, eye_y - ph, ex + pw, eye_y + ph), fill="#020617")
                draw.ellipse((ex - int(3 * scale), eye_y - int(4 * scale), ex - int(0.5 * scale), eye_y - int(1.5 * scale)), fill="#FFFFFF")
                draw.ellipse((ex + int(1 * scale), eye_y + int(1 * scale), ex + int(3 * scale), eye_y + int(3 * scale)), fill="#FFFFFF")

        # Nose & Mouth
        ny = py - int(3 * scale)
        draw.polygon([(cx - int(2.5 * scale), ny), (cx + int(2.5 * scale), ny), (cx, ny + int(2.5 * scale))], fill="#F472B6")
        my = py
        if is_speaking:
            mouth_open = int(math.sin(t * 12.0) * 3 * scale) + int(3 * scale)
            draw.ellipse((cx - int(4 * scale), my, cx + int(4 * scale), my + mouth_open), fill="#BE185D", outline="#F472B6", width=int(1.5 * scale))
        else:
            draw.arc((cx - int(7 * scale), my - int(2 * scale), cx, my + int(3 * scale)), start=0, end=180, fill="#E2E8F0", width=int(2 * scale))
            draw.arc((cx, my - int(2 * scale), cx + int(7 * scale), my + int(3 * scale)), start=0, end=180, fill="#E2E8F0", width=int(2 * scale))

        # Paws
        paw_y = py + int(26 * scale)
        pw, ph = int(8 * scale), int(5 * scale)
        draw.ellipse((cx - int(14 * scale) - pw, paw_y - ph, cx - int(14 * scale) + pw, paw_y + ph), fill="#E2E8F0", outline="#3E3E54", width=int(1.5 * scale))
        draw.ellipse((cx + int(14 * scale) - pw, paw_y - ph, cx + int(14 * scale) + pw, paw_y + ph), fill="#E2E8F0", outline="#3E3E54", width=int(1.5 * scale))

    elif pet_type == "bot":
        # 🤖 Cyber Bot
        tg_w, tg_h = int(16 * scale), int(7 * scale)
        draw.ellipse((cx - tg_w, py + int(30 * scale) - tg_h, cx + tg_w, py + int(30 * scale) + tg_h), fill=state_color)

        # Antennae
        draw.line([(cx - int(22 * scale), py - int(16 * scale)), (cx - int(30 * scale), py - int(32 * scale))], fill="#475569", width=int(3 * scale))
        draw.ellipse((cx - int(33 * scale), py - int(36 * scale), cx - int(27 * scale), py - int(28 * scale)), fill=state_color)
        draw.line([(cx + int(22 * scale), py - int(16 * scale)), (cx + int(30 * scale), py - int(32 * scale))], fill="#475569", width=int(3 * scale))
        draw.ellipse((cx + int(27 * scale), py - int(36 * scale), cx + int(33 * scale), py - int(28 * scale)), fill=state_color)

        # Main Chassis
        rw = int(34 * scale)
        draw.ellipse((cx - rw, py - rw, cx + rw, py + rw), fill="#0F172A", outline="#38BDF8", width=int(2.5 * scale))

        # Visor
        vw, vh = int(26 * scale), int(15 * scale)
        draw.rounded_rectangle((cx - vw, py - vh, cx + vw, py + vh), radius=int(8 * scale), fill="#020617", outline=state_color, width=int(1.5 * scale))

        # LED Eyes / Equalizer
        ew, eh = int(6 * scale), int(8 * scale)
        if is_blinking:
            draw.line([(cx - int(13 * scale) - ew, py), (cx - int(13 * scale) + ew, py)], fill=state_color, width=int(3 * scale))
            draw.line([(cx + int(13 * scale) - ew, py), (cx + int(13 * scale) + ew, py)], fill=state_color, width=int(3 * scale))
        elif is_speaking:
            for i, xoff in enumerate((-16, -8, 0, 8, 16)):
                bar_h = int((math.sin(t * 15.0 + i) * 0.5 + 0.5) * (7 * scale)) + int(2 * scale)
                bx = cx + int(xoff * scale)
                draw.line([(bx, py - bar_h), (bx, py + bar_h)], fill=state_color, width=int(2.5 * scale))
        else:
            draw.rounded_rectangle((cx - int(15 * scale) - ew, py - eh, cx - int(15 * scale) + ew, py + eh), radius=int(3 * scale), fill=state_color)
            draw.rounded_rectangle((cx + int(15 * scale) - ew, py - eh, cx + int(15 * scale) + ew, py + eh), radius=int(3 * scale), fill=state_color)

    elif pet_type == "shiba":
        # 🐶 Shiba Inu
        tail_curl = cx + int(24 * scale), py + int(12 * scale)
        draw.arc((tail_curl[0] - int(12 * scale), tail_curl[1] - int(18 * scale), tail_curl[0] + int(14 * scale), tail_curl[1] + int(12 * scale)), start=45, end=270, fill="#D97706", width=int(8 * scale))

        # Body
        bw, bh = int(30 * scale), int(26 * scale)
        draw.ellipse((cx - bw, py + int(8 * scale) - bh, cx + bw, py + int(8 * scale) + bh), fill="#D97706", outline="#B45309", width=int(2 * scale))
        draw.ellipse((cx - int(13 * scale), py + int(10 * scale) - int(15 * scale), cx + int(13 * scale), py + int(10 * scale) + int(15 * scale)), fill="#FEF3C7")

        # Ears
        draw.polygon([(cx - int(26 * scale), py - int(12 * scale)), (cx - int(34 * scale), py - int(42 * scale)), (cx - int(12 * scale), py - int(20 * scale))], fill="#D97706", outline="#B45309")
        draw.polygon([(cx - int(24 * scale), py - int(14 * scale)), (cx - int(30 * scale), py - int(36 * scale)), (cx - int(14 * scale), py - int(20 * scale))], fill="#FEF3C7")
        draw.polygon([(cx + int(12 * scale), py - int(20 * scale)), (cx + int(34 * scale), py - int(42 * scale)), (cx + int(26 * scale), py - int(12 * scale))], fill="#D97706", outline="#B45309")
        draw.polygon([(cx + int(14 * scale), py - int(20 * scale)), (cx + int(30 * scale), py - int(36 * scale)), (cx + int(24 * scale), py - int(14 * scale))], fill="#FEF3C7")

        # Head & Muzzle
        hw, hh = int(34 * scale), int(28 * scale)
        draw.ellipse((cx - hw, py - int(6 * scale) - hh, cx + hw, py - int(6 * scale) + hh), fill="#D97706", outline="#B45309", width=int(2 * scale))
        draw.ellipse((cx - int(22 * scale), py - int(2 * scale), cx + int(22 * scale), py + int(20 * scale)), fill="#FEF3C7")

        # Eyebrow white dots
        draw.ellipse((cx - int(18 * scale), py - int(22 * scale), cx - int(11 * scale), py - int(15 * scale)), fill="#FFFFFF")
        draw.ellipse((cx + int(11 * scale), py - int(22 * scale), cx + int(18 * scale), py - int(15 * scale)), fill="#FFFFFF")

        # Eyes
        eye_y = py - int(8 * scale)
        ew, eh = int(6 * scale), int(8 * scale)
        if is_blinking or is_petting:
            draw.arc((cx - int(15 * scale) - ew, eye_y - eh, cx - int(15 * scale) + ew, eye_y + eh), start=30, end=150, fill="#451A03", width=int(3 * scale))
            draw.arc((cx + int(15 * scale) - ew, eye_y - eh, cx + int(15 * scale) + ew, eye_y + eh), start=30, end=150, fill="#451A03", width=int(3 * scale))
        else:
            for ex in (cx - int(15 * scale), cx + int(15 * scale)):
                draw.ellipse((ex - ew, eye_y - eh, ex + ew, eye_y + eh), fill="#451A03")
                draw.ellipse((ex - int(2 * scale), eye_y - int(4 * scale), ex + int(1 * scale), eye_y - int(1 * scale)), fill="#FFFFFF")

        # Nose & Mouth
        my = py + int(6 * scale)
        draw.ellipse((cx - int(5 * scale), py + int(2 * scale), cx + int(5 * scale), py + int(8 * scale)), fill="#1C1917")
        if is_speaking:
            draw.ellipse((cx - int(4 * scale), py + int(7 * scale), cx + int(4 * scale), py + int(16 * scale)), fill="#F43F5E")
        else:
            draw.arc((cx - int(7 * scale), my - int(2 * scale), cx, my + int(4 * scale)), start=0, end=180, fill="#78350F", width=int(2 * scale))
            draw.arc((cx, my - int(2 * scale), cx + int(7 * scale), my + int(4 * scale)), start=0, end=180, fill="#78350F", width=int(2 * scale))

        # Collar
        draw.line([(cx - int(16 * scale), py + int(18 * scale)), (cx + int(16 * scale), py + int(18 * scale))], fill="#EF4444", width=int(3.5 * scale))
        draw.ellipse((cx - int(5 * scale), py + int(16 * scale), cx + int(5 * scale), py + int(26 * scale)), fill=state_color, outline="#FFFFFF", width=int(1.5 * scale))

    elif pet_type == "dragon":
        # 🐲 Baby Drake
        wing_flap = math.sin(t * 6.0) * 0.25
        p_lwing = [(cx - int(16 * scale), py + int(2 * scale)), (cx - int(42 * scale), py - int(22 * scale) + int(wing_flap * 15)), (cx - int(36 * scale), py + int(8 * scale))]
        draw.polygon(p_lwing, fill="#059669", outline="#047857")
        p_rwing = [(cx + int(16 * scale), py + int(2 * scale)), (cx + int(42 * scale), py - int(22 * scale) + int(wing_flap * 15)), (cx + int(36 * scale), py + int(8 * scale))]
        draw.polygon(p_rwing, fill="#059669", outline="#047857")

        # Body
        bw, bh = int(30 * scale), int(26 * scale)
        draw.ellipse((cx - bw, py + int(8 * scale) - bh, cx + bw, py + int(8 * scale) + bh), fill="#10B981", outline="#047857", width=int(2 * scale))
        draw.ellipse((cx - int(13 * scale), py + int(9 * scale) - int(15 * scale), cx + int(13 * scale), py + int(9 * scale) + int(15 * scale)), fill="#FDE68A")

        # Golden Horns
        draw.polygon([(cx - int(15 * scale), py - int(22 * scale)), (cx - int(24 * scale), py - int(44 * scale)), (cx - int(7 * scale), py - int(26 * scale))], fill="#F59E0B", outline="#D97706")
        draw.polygon([(cx + int(7 * scale), py - int(26 * scale)), (cx + int(24 * scale), py - int(44 * scale)), (cx + int(15 * scale), py - int(22 * scale))], fill="#F59E0B", outline="#D97706")

        # Head & Snout
        hw, hh = int(32 * scale), int(26 * scale)
        draw.ellipse((cx - hw, py - int(6 * scale) - hh, cx + hw, py - int(6 * scale) + hh), fill="#10B981", outline="#047857", width=int(2 * scale))
        draw.ellipse((cx - int(17 * scale), py - int(2 * scale), cx + int(17 * scale), py + int(15 * scale)), fill="#34D399")
        draw.ellipse((cx - int(5 * scale), py + int(2 * scale), cx - int(2 * scale), py + int(5 * scale)), fill="#065F46")
        draw.ellipse((cx + int(2 * scale), py + int(2 * scale), cx + int(5 * scale), py + int(5 * scale)), fill="#065F46")

        # Eyes
        eye_y = py - int(9 * scale)
        ew, eh = int(6 * scale), int(9 * scale)
        if is_blinking or is_petting:
            draw.line([(cx - int(15 * scale) - ew, eye_y), (cx - int(15 * scale) + ew, eye_y)], fill="#065F46", width=int(3 * scale))
            draw.line([(cx + int(15 * scale) - ew, eye_y), (cx + int(15 * scale) + ew, eye_y)], fill="#065F46", width=int(3 * scale))
        else:
            for ex in (cx - int(15 * scale), cx + int(15 * scale)):
                draw.ellipse((ex - ew, eye_y - eh, ex + ew, eye_y + eh), fill="#F59E0B")
                draw.ellipse((ex - int(2 * scale), eye_y - eh + 2, ex + int(2 * scale), eye_y + eh - 2), fill="#065F46")
                draw.ellipse((ex - int(2 * scale), eye_y - int(4 * scale), ex, eye_y - int(2 * scale)), fill="#FFFFFF")

    im_final = im.resize((size, size), Image.Resampling.LANCZOS)
    return im_final


class FloatingAvatar:
    """OpenPets-inspired interactive Windows desktop AI companion for Kratos."""

    def __init__(
        self,
        image_path: str = "kratos-illu.png",
        status_hub: LiveStatusHub | None = None,
        on_text_submit: Callable[[str], Any] | None = None,
        on_screen_capture: Callable[[], Any] | None = None,
        on_mute_toggle: Callable[[], Any] | None = None,
        on_interrupt: Callable[[], Any] | None = None,
        web_url: str = "http://127.0.0.1:8000",
        avatar_size: int = 120,
        pet_breed: str = "kitty",
    ) -> None:
        self.image_path = os.path.abspath(image_path)
        self.status_hub = status_hub
        self.on_text_submit = on_text_submit
        self.on_screen_capture = on_screen_capture
        self.on_mute_toggle = on_mute_toggle
        self.on_interrupt = on_interrupt
        self.web_url = web_url

        self.avatar_size = avatar_size
        self.pet_breed = pet_breed.lower()
        self.canvas_width = 260
        self.canvas_height = 280

        self.current_state: LiveState = LiveState.CONNECTING
        self.current_transcript: str = ""
        self.is_docked: bool = False
        self.text_entry_visible: bool = False
        self.action_bar_visible: bool = False
        self.is_muted: bool = False

        # GUI handles
        self._root: Any = None
        self._canvas: Any = None
        self._chat_window_item: Any = None
        self._chat_frame: Any = None
        self._entry: Any = None
        self._pet_item: Any = None
        self._aura_ring_items: list[Any] = []
        self._speech_bubble_items: list[Any] = []
        self._action_bar_items: list[Any] = []
        self._action_buttons: list[dict[str, Any]] = []
        self._heart_items: list[Any] = []

        # Animation states
        self._anim_tick: float = 0.0
        self._blink_counter: int = 0
        self._is_blinking: bool = False
        self._petting_ticks: int = 0
        self._photo_cache: Any = None
        self._photo_docked: Any = None

        # Timers & Interactions
        self._hide_action_bar_timer: Any = None
        self._speech_bubble_timer: Any = None
        self._hovered_btn_idx: int = -1
        self._drag_start_x: int = 0
        self._drag_start_y: int = 0
        self._potential_pet_click: bool = False
        self._last_undocked_x: int = 100
        self._last_undocked_y: int = 100

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def set_pet_breed(self, breed: str) -> None:
        """Dynamically switches pet companion character."""
        valid_breeds = ("kitty", "bot", "shiba", "dragon", "custom")
        breed_clean = breed.lower().strip()
        if breed_clean in valid_breeds:
            self.pet_breed = breed_clean
            logger.info(f"[FloatingAvatar] Switched pet companion breed to '{self.pet_breed}'")
            if self._root:
                self._update_pet_sprite()

    def start(self) -> None:
        """Starts the Tkinter desktop pet avatar thread."""
        if self._thread and self._thread.is_alive():
            return

        if os.environ.get("KRATOS_HEADLESS", "").lower() in ("1", "true", "yes"):
            logger.info("[FloatingAvatar] Headless / Test environment detected. Skipping Tkinter window loop.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_gui, name="KratosOpenPetsAvatar", daemon=True)
        self._thread.start()
        logger.info("[FloatingAvatar] Desktop AI Pet GUI thread started.")

    def stop(self) -> None:
        """Gracefully tears down the pet GUI."""
        self._stop_event.set()
        if self._root:
            try:
                self._root.after(0, self._destroy_gui)
            except Exception as e:
                logger.debug(f"[FloatingAvatar] Teardown dispatch error: {e}")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        logger.info("[FloatingAvatar] Desktop AI Pet GUI stopped.")

    def _destroy_gui(self) -> None:
        try:
            if self._root:
                self._root.destroy()
        except Exception as e:
            logger.debug(f"[FloatingAvatar] Destroy error: {e}")
        finally:
            self._root = None
            self._canvas = None

    def _run_gui(self) -> None:
        """Main Tkinter execution loop."""
        import tkinter as tk

        try:
            self._root = tk.Tk()
        except Exception as e:
            logger.warning(f"[FloatingAvatar] Cannot initialize Tk display: {e}")
            return

        self._root.title("Kratos AI Pet")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)

        try:
            self._root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except Exception as e:
            logger.warning(f"[FloatingAvatar] Transparent color not supported: {e}")

        self._root.configure(bg=TRANSPARENT_COLOR)

        # Initial screen placement: bottom right corner
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        start_x = screen_w - self.canvas_width - 40
        start_y = screen_h - self.canvas_height - 90
        self._last_undocked_x = start_x
        self._last_undocked_y = start_y
        self._root.geometry(f"{self.canvas_width}x{self.canvas_height}+{start_x}+{start_y}")

        # Transparent Canvas
        self._canvas = tk.Canvas(
            self._root,
            width=self.canvas_width,
            height=self.canvas_height,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            cursor="arrow",
        )
        self._canvas.pack(fill="both", expand=True)

        self._setup_canvas_elements()
        self._setup_event_bindings()

        # Connect status hub
        if self.status_hub:
            self.status_hub.subscribe(self._on_status_updated)

        # Kickoff animation loop
        self._animate_loop()

        try:
            self._root.mainloop()
        except Exception as e:
            logger.warning(f"[FloatingAvatar] Mainloop error: {e}")

    def _setup_canvas_elements(self) -> None:
        """Initializes canvas shapes, action bar, pet sprite, and speech bubbles."""
        import tkinter as tk

        cx = self.canvas_width // 2
        cy = 190

        # Clean presentation without distracting outer ring lights
        self._aura_ring_items = []

        # Pet Sprite Item
        init_frame = render_openpet_frame(
            pet_type=self.pet_breed,
            size=self.avatar_size,
            state_color=STATE_COLORS.get(self.current_state, "#06B6D4"),
            custom_image_path=self.image_path,
        )
        self._photo_cache = ImageTk.PhotoImage(init_frame)
        self._pet_item = self._canvas.create_image(cx, cy, image=self._photo_cache)

        # Docked compact avatar photo
        docked_frame = render_openpet_frame(
            pet_type=self.pet_breed,
            size=50,
            state_color=STATE_COLORS.get(self.current_state, "#06B6D4"),
            custom_image_path=self.image_path,
        )
        self._photo_docked = ImageTk.PhotoImage(docked_frame)

        # Petting Reaction Heart Particles (hidden by default)
        h1 = self._canvas.create_text(cx - 30, cy - 60, text="❤️", fill="#F43F5E", font=("Segoe UI Emoji", 14), state="hidden")
        h2 = self._canvas.create_text(cx + 32, cy - 64, text="✨", fill="#FDE047", font=("Segoe UI Emoji", 13), state="hidden")
        h3 = self._canvas.create_text(cx, cy - 75, text="💖", fill="#EC4899", font=("Segoe UI Emoji", 16), state="hidden")
        self._heart_items = [h1, h2, h3]

        # Action Bar (Pill background + 4 buttons: Chat, Mic, Vision, 3 Dots)
        # Bar bounds: x1=25, y1=62, x2=235, y2=106
        bar_bg = self._draw_rounded_polygon(25, 62, 235, 106, r=16, fill="#0F172A", outline="#38BDF8", width=1.5)
        self._action_bar_items.append(bar_bg)

        # 4 Hover Options: Chat, Mic, Vision, 3 Dots
        # Centers at y=84, x = 55, 105, 155, 205
        btn_defs = [
            {"id": "chat", "label": "Chat", "icon": "💬", "cx": 55, "cy": 84, "handler": self.toggle_chat},
            {"id": "mic", "label": "Mic", "icon": "🎙️", "cx": 105, "cy": 84, "handler": self._trigger_mute_toggle},
            {"id": "vision", "label": "Vision", "icon": "👁️", "cx": 155, "cy": 84, "handler": self._trigger_screen_capture},
            {"id": "more", "label": "More", "icon": "⋯", "cx": 205, "cy": 84, "handler": self._show_context_menu},
        ]

        self._action_buttons = []
        for b in btn_defs:
            bcx, bcy = b["cx"], b["cy"]
            r = 16
            circle = self._canvas.create_oval(bcx - r, bcy - r, bcx + r, bcy + r, fill="#1E293B", outline="#475569", width=1.0)
            text = self._canvas.create_text(bcx, bcy, text=b["icon"], fill="#F8FAFC", font=("Segoe UI Emoji", 11, "bold"))
            self._action_bar_items.extend([circle, text])
            self._action_buttons.append({
                "id": b["id"],
                "circle": circle,
                "text": text,
                "cx": bcx,
                "cy": bcy,
                "r": r,
                "label": b["label"],
                "handler": b["handler"],
            })

        # Mini tooltip text above hovered button
        self._action_tooltip = self._canvas.create_text(130, 48, text="", fill="#38BDF8", font=("Segoe UI", 9, "bold"), state="hidden")
        self._action_bar_items.append(self._action_tooltip)

        # Action bar initially hidden until user hovers
        self._hide_action_bar_immediate()

        # Speech & Thought Bubble (x1=20, y1=10, x2=240, y2=62)
        bubble_bg = self._draw_rounded_polygon(20, 10, 240, 62, r=12, fill="#0F172A", outline="#6366F1", width=1.5)
        # Tail pointing towards pet mouth
        tail = self._canvas.create_polygon([(122, 62), (138, 62), (130, 74)], fill="#0F172A", outline="#6366F1")
        bubble_text = self._canvas.create_text(130, 36, text="", fill="#F8FAFC", font=("Segoe UI", 9), width=200, justify="center")
        self._speech_bubble_items = [bubble_bg, tail, bubble_text]
        for it in self._speech_bubble_items:
            self._canvas.itemconfigure(it, state="hidden")

        # Interactive Chat Input Balloon Widget (tk.Frame embedded in canvas)
        self._chat_frame = tk.Frame(self._canvas, bg="#0F172A", highlightbackground="#6366F1", highlightthickness=1.5, bd=0)

        self._entry = tk.Entry(
            self._chat_frame,
            bg="#1E293B",
            fg="#F8FAFC",
            insertbackground="#38BDF8",
            font=("Segoe UI", 9),
            relief="flat",
            bd=3,
        )
        self._entry.pack(side="left", padx=(6, 4), pady=4, fill="x", expand=True)
        self._entry.bind("<Return>", self._handle_entry_submit)
        self._entry.bind("<Escape>", lambda e: self.toggle_chat())

        send_btn = tk.Label(
            self._chat_frame,
            text="➤",
            bg="#4F46E5",
            fg="#FFFFFF",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=7,
            pady=2,
        )
        send_btn.pack(side="left", padx=(0, 4), pady=4)
        send_btn.bind("<Button-1>", self._handle_entry_submit)

        close_btn = tk.Label(
            self._chat_frame,
            text="✕",
            bg="#0F172A",
            fg="#94A3B8",
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=4,
        )
        close_btn.pack(side="right", padx=(0, 6), pady=4)
        close_btn.bind("<Button-1>", lambda e: self.toggle_chat())

        self._chat_window_item = self._canvas.create_window(130, 84, window=self._chat_frame, width=220, height=36, state="hidden")

    def _draw_rounded_polygon(self, x1: int, y1: int, x2: int, y2: int, r: int = 12, **kwargs: Any) -> Any:
        """Draws a smooth rounded rectangle on Tkinter canvas."""
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self._canvas.create_polygon(points, smooth=True, **kwargs)

    def _setup_event_bindings(self) -> None:
        """Binds mouse events for hovering, clicking buttons, pet reactions, and dragging."""
        self._canvas.bind("<Enter>", self._on_canvas_enter)
        self._canvas.bind("<Leave>", self._on_canvas_leave)
        self._canvas.bind("<Motion>", self._on_canvas_motion)

        self._canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self._canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self._canvas.bind("<Double-Button-1>", lambda e: self.toggle_dock())

        self._canvas.bind("<Button-3>", self._show_context_menu)

    def _on_canvas_enter(self, event: Any) -> None:
        if self._hide_action_bar_timer:
            self._root.after_cancel(self._hide_action_bar_timer)
            self._hide_action_bar_timer = None
        if not self.is_docked:
            self._show_action_bar()

    def _on_canvas_leave(self, event: Any) -> None:
        # Reset hovered button aesthetics
        self._reset_button_hover()
        # Schedule auto-hide with 1.4s grace period unless text entry is currently open
        if not self.text_entry_visible and not self.is_docked:
            if self._hide_action_bar_timer:
                self._root.after_cancel(self._hide_action_bar_timer)
            self._hide_action_bar_timer = self._root.after(1400, self._hide_action_bar)

    def _on_canvas_motion(self, event: Any) -> None:
        if self._hide_action_bar_timer:
            self._root.after_cancel(self._hide_action_bar_timer)
            self._hide_action_bar_timer = None

        if not self.is_docked and not self.action_bar_visible:
            self._show_action_bar()

        # Check button hover
        hovered_idx = -1
        if self.action_bar_visible and not self.text_entry_visible:
            for i, b in enumerate(self._action_buttons):
                dx = event.x - b["cx"]
                dy = event.y - b["cy"]
                if (dx * dx + dy * dy) <= (b["r"] * b["r"]):
                    hovered_idx = i
                    break

        if hovered_idx != self._hovered_btn_idx:
            self._hovered_btn_idx = hovered_idx
            self._update_button_hover_state()

    def _update_button_hover_state(self) -> None:
        if not self._canvas:
            return

        if self._hovered_btn_idx >= 0:
            self._canvas.configure(cursor="hand2")
            b = self._action_buttons[self._hovered_btn_idx]
            for i, btn in enumerate(self._action_buttons):
                fill = "#4F46E5" if i == self._hovered_btn_idx else "#1E293B"
                outline = "#38BDF8" if i == self._hovered_btn_idx else "#475569"
                self._canvas.itemconfig(btn["circle"], fill=fill, outline=outline)

            # Update tooltip text
            self._canvas.itemconfig(self._action_tooltip, text=f"• {b['label']} •", state="normal")
            self._canvas.coords(self._action_tooltip, b["cx"], 46)
        else:
            self._canvas.configure(cursor="arrow")
            self._reset_button_hover()

    def _reset_button_hover(self) -> None:
        self._hovered_btn_idx = -1
        if self._canvas:
            for b in self._action_buttons:
                self._canvas.itemconfig(b["circle"], fill="#1E293B", outline="#475569")
            self._canvas.itemconfig(self._action_tooltip, state="hidden")

    def _show_action_bar(self) -> None:
        if self.action_bar_visible or self.is_docked:
            return
        self.action_bar_visible = True
        for it in self._action_bar_items:
            self._canvas.itemconfigure(it, state="normal")
        self._canvas.itemconfig(self._action_tooltip, state="hidden")

    def _hide_action_bar(self) -> None:
        if self.text_entry_visible:
            return
        self.action_bar_visible = False
        self._reset_button_hover()
        for it in self._action_bar_items:
            self._canvas.itemconfigure(it, state="hidden")

    def _hide_action_bar_immediate(self) -> None:
        self.action_bar_visible = False
        self._reset_button_hover()
        for it in self._action_bar_items:
            self._canvas.itemconfigure(it, state="hidden")

    def _on_mouse_down(self, event: Any) -> None:
        # Check if clicked on action buttons
        if self.action_bar_visible and not self.text_entry_visible:
            for b in self._action_buttons:
                dx = event.x - b["cx"]
                dy = event.y - b["cy"]
                if (dx * dx + dy * dy) <= (b["r"] * b["r"]):
                    b["handler"]()
                    return

        # Pet body drag or petting click
        self._drag_start_x = event.x_root - self._root.winfo_x()
        self._drag_start_y = event.y_root - self._root.winfo_y()
        self._potential_pet_click = True

    def _on_mouse_drag(self, event: Any) -> None:
        # Mouse moved: it's a drag, not a petting click
        self._potential_pet_click = False
        if not self.is_docked:
            new_x = event.x_root - self._drag_start_x
            new_y = event.y_root - self._drag_start_y
            self._root.geometry(f"+{new_x}+{new_y}")

    def _on_mouse_up(self, event: Any) -> None:
        if self._potential_pet_click and not self.is_docked:
            # Trigger petting reaction!
            self.trigger_pet_reaction()
        self._potential_pet_click = False

    def trigger_pet_reaction(self) -> None:
        """Triggers a happy petting reaction: hearts, joyful bounce, and sound acknowledgment."""
        self._petting_ticks = 24  # ~1.4 seconds of joyful bounce
        logger.info(f"[FloatingAvatar] Petting reaction triggered on {self.pet_breed}!")

        # Show heart particles
        for h in self._heart_items:
            self._canvas.itemconfigure(h, state="normal")

        # Pet acknowledges with a mini speech bubble if idle
        if not self.current_transcript:
            greetings = {
                "kitty": "Purr... ❤️ Meow!",
                "bot": "Bleep bloop! Systems 100% happy! ✨",
                "shiba": "Woof! Good human! 🐾",
                "dragon": "Rrrr... *sparks tiny ember* 🔥",
                "custom": "Kratos ready and synced!",
            }
            self.show_speech_bubble(greetings.get(self.pet_breed, "❤️ ✨"), duration_sec=2.5)

    def toggle_chat(self) -> None:
        """Toggles interactive chat balloon attached to pet."""
        self.toggle_text_entry()

    def toggle_text_entry(self) -> None:
        """Toggles text entry input balloon."""
        self.text_entry_visible = not self.text_entry_visible
        if self.text_entry_visible:
            # Hide action bar while typing
            self._hide_action_bar_immediate()
            self._canvas.itemconfigure(self._chat_window_item, state="normal")
            self._entry.delete(0, "end")
            self._entry.focus_set()
        else:
            self._canvas.itemconfigure(self._chat_window_item, state="hidden")
            if self._root:
                self._root.focus_set()

    def _handle_entry_submit(self, event: Any = None) -> None:
        """Dispatches submitted chat text to Kratos Live session."""
        text = self._entry.get().strip()
        if text:
            logger.info(f"[FloatingAvatar] Chat message submitted: {text}")
            if self.on_text_submit:
                try:
                    self.on_text_submit(text)
                except Exception as e:
                    logger.warning(f"[FloatingAvatar] Error in text submit callback: {e}")
            self.show_speech_bubble(f"Thinking about:\n'{text[:28]}...'", duration_sec=3.0)
            self._entry.delete(0, "end")
        self.toggle_chat()

    def show_speech_bubble(self, text: str, duration_sec: float = 4.0) -> None:
        """Displays comic speech / thought bubble with text."""
        if not self._root or not self._canvas or len(self._speech_bubble_items) < 3:
            return

        clean_text = text.strip()
        if len(clean_text) > 80:
            clean_text = clean_text[:77] + "..."

        try:
            self._canvas.itemconfig(self._speech_bubble_items[2], text=clean_text)
            for it in self._speech_bubble_items:
                self._canvas.itemconfigure(it, state="normal")
        except Exception:
            pass

        if self._speech_bubble_timer:
            try:
                self._root.after_cancel(self._speech_bubble_timer)
            except Exception:
                pass
        try:
            self._speech_bubble_timer = self._root.after(int(duration_sec * 1000), self._hide_speech_bubble)
        except Exception:
            pass

    def _hide_speech_bubble(self) -> None:
        if self._canvas:
            for it in self._speech_bubble_items:
                self._canvas.itemconfigure(it, state="hidden")
        self._speech_bubble_timer = None

    def toggle_dock(self) -> None:
        """Docks / undocks the pet to the screen edge."""
        if not self._root or not self._canvas:
            return

        screen_w = self._root.winfo_screenwidth()
        current_y = self._root.winfo_y()

        if not self.is_docked:
            self._last_undocked_x = self._root.winfo_x()
            self._last_undocked_y = current_y

            dock_x = screen_w - 56
            self._root.geometry(f"56x56+{dock_x}+{current_y}")
            self._canvas.itemconfig(self._pet_item, image=self._photo_docked)
            self._canvas.coords(self._pet_item, 28, 28)

            for r in self._aura_ring_items:
                self._canvas.itemconfigure(r, state="hidden")
            self._hide_action_bar_immediate()
            self._hide_speech_bubble()
            if self.text_entry_visible:
                self.toggle_chat()
            self.is_docked = True
        else:
            self._root.geometry(f"{self.canvas_width}x{self.canvas_height}+{self._last_undocked_x}+{self._last_undocked_y}")
            cx = self.canvas_width // 2
            cy = 190
            self._canvas.itemconfig(self._pet_item, image=self._photo_cache)
            self._canvas.coords(self._pet_item, cx, cy)

            for r in self._aura_ring_items:
                self._canvas.itemconfigure(r, state="normal")
            self.is_docked = False

    def _show_context_menu(self, event: Any = None) -> None:
        """Displays Windows-native 3-dots popup menu."""
        import tkinter as tk

        menu = tk.Menu(self._root, tearoff=0, bg="#0F172A", fg="#F8FAFC", activebackground="#4F46E5", activeforeground="#FFFFFF")

        # Companion selection submenu
        pet_menu = tk.Menu(menu, tearoff=0, bg="#0F172A", fg="#F8FAFC", activebackground="#4F46E5", activeforeground="#FFFFFF")
        pet_menu.add_command(label="🐱  Cyber Kitty", command=lambda: self.set_pet_breed("kitty"))
        pet_menu.add_command(label="🤖  Cyber Bot", command=lambda: self.set_pet_breed("bot"))
        pet_menu.add_command(label="🐶  Shiba Inu", command=lambda: self.set_pet_breed("shiba"))
        pet_menu.add_command(label="🐲  Baby Drake", command=lambda: self.set_pet_breed("dragon"))
        pet_menu.add_command(label="🔮  Kratos Illu", command=lambda: self.set_pet_breed("custom"))
        menu.add_cascade(label="🐾  Select Pet Companion", menu=pet_menu)

        menu.add_separator()
        menu.add_command(label="💬  Chat with Pet", command=self.toggle_chat)
        menu.add_command(label="🎙️  Toggle Microphone Mute", command=self._trigger_mute_toggle)
        menu.add_command(label="👁️  Look at Screen (Vision)", command=self._trigger_screen_capture)
        menu.add_separator()
        menu.add_command(label="📌  " + ("Undock Pet" if self.is_docked else "Dock to Screen Edge"), command=self.toggle_dock)
        menu.add_command(label="🌐  Open Web Dashboard", command=lambda: webbrowser.open(self.web_url))
        menu.add_separator()
        menu.add_command(label="✕   Hide Pet", command=self.stop)

        try:
            if event and hasattr(event, "x_root"):
                menu.tk_popup(event.x_root, event.y_root)
            else:
                x = self._root.winfo_x() + 190
                y = self._root.winfo_y() + 90
                menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _trigger_screen_capture(self) -> None:
        logger.info("[FloatingAvatar] Vision screen capture requested.")
        self.show_speech_bubble("Scanning screen... 👁️", duration_sec=2.5)
        if self.on_screen_capture:
            try:
                self.on_screen_capture()
            except Exception as e:
                logger.warning(f"[FloatingAvatar] Screen capture trigger error: {e}")

    def _trigger_mute_toggle(self) -> None:
        self.is_muted = not self.is_muted
        mic_icon = "🔇" if self.is_muted else "🎙️"
        logger.info(f"[FloatingAvatar] Mic mute toggled (is_muted={self.is_muted}).")
        # Update button icon on canvas
        if self._canvas:
            for b in self._action_buttons:
                if b["id"] == "mic":
                    try:
                        self._canvas.itemconfig(b["text"], text=mic_icon)
                        fill = "#EF4444" if self.is_muted else "#1E293B"
                        self._canvas.itemconfig(b["circle"], fill=fill)
                    except Exception:
                        pass

        msg = "Microphone muted 🔇" if self.is_muted else "Microphone unmuted 🎙️"
        self.show_speech_bubble(msg, duration_sec=2.0)

        if self.on_mute_toggle:
            try:
                self.on_mute_toggle()
            except Exception as e:
                logger.warning(f"[FloatingAvatar] Mute toggle error: {e}")

    def _on_status_updated(self, status: LiveStatus) -> None:
        """Reactive callback from LiveStatusHub."""
        if not self._root:
            return

        def _apply() -> None:
            self.current_state = status.current_state
            if status.last_transcript and status.last_transcript != self.current_transcript:
                self.current_transcript = status.last_transcript
                self.show_speech_bubble(self.current_transcript, duration_sec=5.0)

        try:
            self._root.after(0, _apply)
        except Exception as e:
            logger.debug(f"[FloatingAvatar] Status apply schedule error: {e}")

    def _update_pet_sprite(self) -> None:
        """Re-renders the pet frame with the current animation cycle."""
        if not self._canvas or self.is_docked:
            return

        state_color = STATE_COLORS.get(self.current_state, "#06B6D4")
        is_speaking = (self.current_state == LiveState.SPEAKING)
        is_petting = (self._petting_ticks > 0)

        frame = render_openpet_frame(
            pet_type=self.pet_breed,
            size=self.avatar_size,
            state_color=state_color,
            t=self._anim_tick,
            is_blinking=self._is_blinking,
            is_speaking=is_speaking,
            is_petting=is_petting,
            custom_image_path=self.image_path,
        )
        self._photo_cache = ImageTk.PhotoImage(frame)
        self._canvas.itemconfig(self._pet_item, image=self._photo_cache)

    def _animate_loop(self) -> None:
        """Smooth 18 FPS animation loop for pet bobbing, blinking, and glowing auras."""
        if not self._root or self._stop_event.is_set():
            return

        self._anim_tick += 0.12
        self._blink_counter += 1

        # Periodic blinking (every 40-70 frames for 2 frames)
        if self._blink_counter > 55:
            self._is_blinking = True
            if self._blink_counter > 58:
                self._is_blinking = False
                self._blink_counter = 0

        # Decrement petting reaction ticks
        if self._petting_ticks > 0:
            self._petting_ticks -= 1
            if self._petting_ticks == 0:
                for h in self._heart_items:
                    self._canvas.itemconfigure(h, state="hidden")

        if not self.is_docked:
            self._update_pet_sprite()

        try:
            self._root.after(55, self._animate_loop)
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)


# Alias for backwards compatibility and expressive naming
AIPetAvatar = FloatingAvatar
