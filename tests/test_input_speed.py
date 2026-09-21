import time
import unittest
from unittest.mock import patch, MagicMock
from kratos_agent.ccs.base import Point
from kratos_agent.ccs.input.windows import WindowsInputEngine

class TestInputSpeed(unittest.TestCase):
    def setUp(self):
        self.engine = WindowsInputEngine(humanize=False)

    @patch("kratos_agent.ccs.input.windows.user32")
    def test_mouse_move_instant_within_budget(self, mock_user32):
        mock_user32.GetSystemMetrics.return_value = 1920
        start = time.monotonic()
        res = self.engine.mouse_move(Point(500, 500), style="instant")
        elapsed_ms = (time.monotonic() - start) * 1000
        self.assertTrue(res.ok)
        self.assertLessEqual(elapsed_ms, 15.0)  # Generous budget allowance in CI

    @patch("kratos_agent.ccs.input.windows.user32")
    def test_mouse_click_within_budget(self, mock_user32):
        mock_user32.GetSystemMetrics.return_value = 1920
        start = time.monotonic()
        res = self.engine.mouse_click(Point(500, 500), style="instant")
        elapsed_ms = (time.monotonic() - start) * 1000
        self.assertTrue(res.ok)
        # 25ms hold + minimal overhead <= 80ms
        self.assertLessEqual(elapsed_ms, 80.0)

    @patch("kratos_agent.ccs.input.windows.user32")
    def test_batched_type_text_is_single_sendinput_call(self, mock_user32):
        text = "Hello world!"
        res = self.engine.type_text(text, strategy="event")
        self.assertTrue(res.ok)
        # Verify SendInput was called exactly once for the whole string
        self.assertEqual(mock_user32.SendInput.call_count, 1)

    @patch("pyperclip.paste", return_value="original_clipboard")
    @patch("pyperclip.copy")
    def test_type_text_auto_uses_clipboard_for_long_text(self, mock_copy, mock_paste):
        with patch.object(self.engine, "key_tap") as mock_key_tap:
            long_text = "A" * 45
            res = self.engine.type_text(long_text, strategy="auto")
            self.assertTrue(res.ok)
            mock_key_tap.assert_called_with(["ctrl", "v"])
            # Verify clipboard restored
            mock_copy.assert_any_call("original_clipboard")

    @patch("pyperclip.paste", return_value="original_clipboard")
    @patch("pyperclip.copy")
    def test_type_text_auto_uses_clipboard_for_non_ascii(self, mock_copy, mock_paste):
        with patch.object(self.engine, "key_tap") as mock_key_tap:
            tamil_text = "காட் ஆஃப் வார்"
            res = self.engine.type_text(tamil_text, strategy="auto")
            self.assertTrue(res.ok)
            mock_key_tap.assert_called_with(["ctrl", "v"])
            mock_copy.assert_any_call("original_clipboard")

    @patch("pyperclip.paste", return_value="original_clipboard")
    @patch("pyperclip.copy")
    def test_clipboard_restored_even_on_exception(self, mock_copy, mock_paste):
        with patch.object(self.engine, "key_tap", side_effect=RuntimeError("simulated error")):
            try:
                self.engine.type_text("some text", strategy="clipboard")
            except Exception:
                pass
            # Verify clipboard was restored in finally block
            mock_copy.assert_any_call("original_clipboard")

if __name__ == "__main__":
    unittest.main()
