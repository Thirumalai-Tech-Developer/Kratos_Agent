"""Unit tests for shell detection, PowerShell command rendering, and CLIXML parsing."""
from __future__ import annotations
import unittest

from kratos_agent.system.shell.base import CommandResult, ShellInfo
from kratos_agent.system.shell.detect import detect_shell
from kratos_agent.system.shell.output_parser import normalize_command_output, parse_clixml
from kratos_agent.system.shell.renderer import render_powershell_script, render_command_argv


class TestShellAbstraction(unittest.TestCase):
    def test_shell_detection(self) -> None:
        sh = detect_shell()
        self.assertIsInstance(sh, ShellInfo)
        self.assertIn(sh.name, ("powershell", "pwsh", "bash", "sh", "zsh"))
        self.assertIn(sh.platform, ("windows", "linux", "darwin"))

    def test_powershell_command_rendering_and_operator(self) -> None:
        # On PowerShell 5.1 without && support, && must be translated to '; if ($?) { ... }'
        cmd = "python --version && pip --version"
        rendered = render_powershell_script(cmd, supports_and=False)
        self.assertNotIn("&&", rendered)
        self.assertIn("python --version; if ($?) { pip --version }", rendered)

    def test_powershell_command_rendering_or_operator(self) -> None:
        cmd = "pytest || echo failed"
        rendered = render_powershell_script(cmd, supports_and=False)
        self.assertNotIn("||", rendered)
        self.assertIn("pytest; if (-not $?) { echo failed }", rendered)

    def test_powershell_translates_cmd_cd_drive_switch(self) -> None:
        cmd = r"cd /d C:\Users\thiru\Documents\Kratos_Agent; if ($?) { uv run kratos }"
        rendered = render_powershell_script(cmd, supports_and=False)
        self.assertNotIn("cd /d", rendered.lower())
        self.assertIn("Set-Location -LiteralPath 'C:\\Users\\thiru\\Documents\\Kratos_Agent'", rendered)
    def test_render_command_argv(self) -> None:
        argv = render_command_argv("Get-Process")
        self.assertIsInstance(argv, list)
        self.assertGreater(len(argv), 1)

    def test_clixml_parsing_error_stream(self) -> None:
        raw_clixml = (
            "#< CLIXML\n"
            '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
            '<S S="Error">The token \'&amp;&amp;\' is not a valid statement separator in this version._x000D__x000A_</S>'
            "</Objs>"
        )
        parsed = parse_clixml(raw_clixml)
        self.assertIn("The token '&&' is not a valid statement separator", parsed)
        self.assertNotIn("<Objs", parsed)
        self.assertNotIn("_x000D__x000A_", parsed)

    def test_clixml_progress_record_stripping(self) -> None:
        raw_progress = (
            '#< CLIXML\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
            '<Obj S="progress" RefId="0"><TN RefId="0"><T>System.Management.Automation.PSCustomObject</T></TN>'
            '<MS><PR N="Record"><AV>Preparing modules for first use.</AV><T>Completed</T></PR></MS></Obj>'
            '<S S="Error">Real error message</S></Objs>'
        )
        norm = normalize_command_output(raw_progress, exit_code=1)
        self.assertFalse(norm.success)
        self.assertIn("Real error message", norm.stderr)
        self.assertNotIn("Preparing modules", norm.stderr)
        self.assertNotIn("<Obj S=\"progress\"", norm.stderr)


if __name__ == "__main__":
    unittest.main()
