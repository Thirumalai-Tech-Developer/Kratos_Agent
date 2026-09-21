import unittest
from kratos_agent.core.command_lint import lint_command

class TestCommandLint(unittest.TestCase):
    def test_known_bad_commands(self):
        bad_commands = [
            "rm -rf /",
            "rm -rf / ",
            "format c:",
            "del /f /s /q C:\\",
            ":(){ :|:& };:",
            "dd if=/dev/zero of=/dev/sda",
        ]
        for cmd in bad_commands:
            res = lint_command(cmd, "bash")
            self.assertFalse(res.ok, f"Should reject dangerous command: {cmd}")
            self.assertEqual(res.code, "FORBIDDEN_TARGET")

    def test_observed_failing_command_unbalanced_quote(self):
        # The exact bug: god's war with single quotes in powershell
        failing_cmd = "Start-Process chrome 'https://www.youtube.com/results?search_query=god's war'"
        res = lint_command(failing_cmd, "powershell")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "COMMAND_PARSE_RISK")
        self.assertTrue(any("unbalanced '" in p for p in res.problems))

    def test_raw_space_in_url(self):
        cmd = "curl https://example.com/api?q=hello world"
        res = lint_command(cmd, "powershell")
        self.assertFalse(res.ok)
        self.assertTrue(any("contains a raw space" in p for p in res.problems))

    def test_prose_in_command(self):
        # Tamil narration leak or natural sentences
        cmd = "கண்டிப்பாக, நிலைமையை நான் சரிபார்க்கிறேன்"
        res = lint_command(cmd, "powershell")
        self.assertFalse(res.ok)
        self.assertTrue(any("natural-language prose" in p for p in res.problems))

    def test_benign_commands_pass(self):
        good_commands = [
            "dir",
            "git status",
            "npm run build",
            "pytest -v",
            "python -c \"print('hello')\"",
            "echo 'hello world'",
        ]
        for cmd in good_commands:
            res = lint_command(cmd, "powershell")
            self.assertTrue(res.ok, f"Benign command failed: {cmd}, problems: {res.problems}")
            self.assertIsNotNone(res.suggestion)

if __name__ == "__main__":
    unittest.main()
