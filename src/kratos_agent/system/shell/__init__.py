"""Kratos Shell Abstraction Layer."""
from kratos_agent.system.shell.base import CommandResult, ShellInfo
from kratos_agent.system.shell.detect import detect_shell, get_current_shell
from kratos_agent.system.shell.output_parser import (
    normalize_command_output,
    parse_clixml,
)
from kratos_agent.system.shell.renderer import (
    render_command_argv,
    render_powershell_script,
)

__all__ = [
    "CommandResult",
    "ShellInfo",
    "detect_shell",
    "get_current_shell",
    "normalize_command_output",
    "parse_clixml",
    "render_command_argv",
    "render_powershell_script",
]
