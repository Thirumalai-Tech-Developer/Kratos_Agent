import unittest
from unittest.mock import patch, MagicMock
from kratos_agent.ccs.input.windows import WindowsInputEngine, KEYEVENTF_UNICODE

class TestUnicodeTyping(unittest.TestCase):
    def setUp(self):
        self.engine = WindowsInputEngine(humanize=False)

    @patch("kratos_agent.ccs.input.windows.user32")
    def test_unicode_event_injection(self, mock_user32):
        # Tamil, emoji, CJK
        test_strings = [
            "காட் ஆஃப் வார்",
            "🎮 ⚔️ 🔥",
            "战神 갓 오브 워",
            "سلام دنیا",
        ]
        for s in test_strings:
            mock_user32.reset_mock()
            res = self.engine.type_text(s, strategy="event")
            self.assertTrue(res.ok)
            self.assertEqual(mock_user32.SendInput.call_count, 1)

    @patch("pyperclip.paste", return_value="")
    @patch("pyperclip.copy")
    def test_unicode_clipboard_strategy(self, mock_copy, mock_paste):
        with patch.object(self.engine, "key_tap") as mock_key_tap:
            text = "காட் ஆஃப் வார் - God of War"
            res = self.engine.type_text(text, strategy="clipboard")
            self.assertTrue(res.ok)
            mock_copy.assert_any_call(text)
            mock_key_tap.assert_called_with(["ctrl", "v"])

if __name__ == "__main__":
    unittest.main()
