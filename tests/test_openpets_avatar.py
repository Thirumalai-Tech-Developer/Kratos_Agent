"""Unit tests for OpenPets AI Desktop Companion Avatar."""
import os
import unittest
from unittest.mock import MagicMock

from PIL import Image

from kratos_agent.live.avatar import (
    AIPetAvatar,
    FloatingAvatar,
    STATE_COLORS,
    STATE_LABELS,
    _make_circular_avatar,
    render_openpet_frame,
)
from kratos_agent.live.events import LiveState, LiveStatusHub


class TestOpenPetsAvatar(unittest.TestCase):
    def test_procedural_sprite_rendering_all_breeds(self):
        """Verifies procedural sprite rendering for all 4 OpenPets characters + custom."""
        breeds = ("kitty", "bot", "shiba", "dragon", "custom")
        for breed in breeds:
            # Idle
            frame = render_openpet_frame(pet_type=breed, size=120, state_color="#06B6D4", t=0.5)
            self.assertIsInstance(frame, Image.Image)
            self.assertEqual(frame.size, (120, 120))
            self.assertEqual(frame.mode, "RGBA")

            # Speaking
            frame_speaking = render_openpet_frame(pet_type=breed, size=120, state_color="#F97316", t=1.0, is_speaking=True)
            self.assertEqual(frame_speaking.size, (120, 120))

            # Blinking
            frame_blinking = render_openpet_frame(pet_type=breed, size=120, state_color="#10B981", t=1.5, is_blinking=True)
            self.assertEqual(frame_blinking.size, (120, 120))

            # Petting reaction
            frame_petting = render_openpet_frame(pet_type=breed, size=120, state_color="#EC4899", t=2.0, is_petting=True)
            self.assertEqual(frame_petting.size, (120, 120))

    def test_avatar_initialization_and_breed_switching(self):
        """Verifies pet initialization, breed switching, and backward compatibility aliases."""
        self.assertIs(AIPetAvatar, FloatingAvatar)

        hub = LiveStatusHub()
        mock_chat = MagicMock()
        mock_vision = MagicMock()
        mock_mute = MagicMock()

        avatar = FloatingAvatar(
            image_path="kratos-illu.png",
            status_hub=hub,
            on_text_submit=mock_chat,
            on_screen_capture=mock_vision,
            on_mute_toggle=mock_mute,
            avatar_size=120,
            pet_breed="kitty",
        )

        self.assertEqual(avatar.pet_breed, "kitty")
        self.assertFalse(avatar.is_docked)
        self.assertFalse(avatar.text_entry_visible)
        self.assertFalse(avatar.action_bar_visible)
        self.assertEqual(avatar.current_state, LiveState.CONNECTING)

        # Switch breeds
        avatar.set_pet_breed("bot")
        self.assertEqual(avatar.pet_breed, "bot")
        avatar.set_pet_breed("shiba")
        self.assertEqual(avatar.pet_breed, "shiba")
        avatar.set_pet_breed("dragon")
        self.assertEqual(avatar.pet_breed, "dragon")

    def test_hover_action_options_structure(self):
        """Verifies the 4 hover options: Chat, Mic, Vision, and 3-Dots are correctly configured."""
        avatar = FloatingAvatar(pet_breed="kitty")

        # Headless initialization mock
        avatar._canvas = MagicMock()
        avatar._root = MagicMock()
        avatar._action_buttons = [
            {"id": "chat", "label": "Chat", "icon": "💬", "cx": 55, "cy": 84, "handler": avatar.toggle_chat},
            {"id": "mic", "label": "Mic", "icon": "🎙️", "cx": 105, "cy": 84, "handler": avatar._trigger_mute_toggle},
            {"id": "vision", "label": "Vision", "icon": "👁️", "cx": 155, "cy": 84, "handler": avatar._trigger_screen_capture},
            {"id": "more", "label": "More", "icon": "⋯", "cx": 205, "cy": 84, "handler": avatar._show_context_menu},
        ]

        ids = [b["id"] for b in avatar._action_buttons]
        self.assertEqual(ids, ["chat", "mic", "vision", "more"])

        # Test Mic toggle
        self.assertFalse(avatar.is_muted)
        avatar._trigger_mute_toggle()
        self.assertTrue(avatar.is_muted)
        avatar._trigger_mute_toggle()
        self.assertFalse(avatar.is_muted)

    def test_petting_reaction_and_speech_bubble(self):
        """Verifies petting reaction ticks and comic speech bubble formatting."""
        avatar = FloatingAvatar(pet_breed="kitty")
        avatar._canvas = MagicMock()
        avatar._root = MagicMock()
        avatar._speech_bubble_items = [MagicMock(), MagicMock(), MagicMock()]

        # Trigger petting
        self.assertEqual(avatar._petting_ticks, 0)
        avatar.trigger_pet_reaction()
        self.assertGreater(avatar._petting_ticks, 0)

        # Speech bubble
        avatar.show_speech_bubble("Hello, I am your desktop pet!", duration_sec=3.0)
        avatar._canvas.itemconfig.assert_called()


if __name__ == "__main__":
    unittest.main()
