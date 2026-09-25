import unittest

from kratos_agent.core.tool_runtime import _terminal_command_failed


class TerminalExitDetectionTests(unittest.TestCase):
    def test_terminal_command_failure_formats_are_detected(self):
        self.assertTrue(_terminal_command_failed("Command exited with status 1.\nSyntaxError"))
        self.assertTrue(_terminal_command_failed("Exit Code: 2\nmissing file"))
        self.assertFalse(_terminal_command_failed("Command exited with status 0.\nOK"))
