"""Kratos Shell Abstraction Layer."""
from kratos_agent.system.shell.base import ShellInfo, CommandResult
from kratos_agent.system.shell.detect import detect_shell, get_current_shell
from kratos_agent.system.shell.output_parser import parse_clixml, normalize_command_output
from kratos_agent.system.shell.renderer import render_powershell_script, render_command_argv

__all__ = [
    "ShellInfo",
    "CommandResult",
    "detect_shell",
    "get_current_shell",
    "parse_clixml",
    "normalize_command_output",
    "render_powershell_script",
    "render_command_argv",
]
