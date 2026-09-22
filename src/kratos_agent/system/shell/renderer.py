"""Command renderer and translator for multi-shell compatibility."""
from __future__ import annotations
import re
from typing import List, Optional

from kratos_agent.system.shell.base import ShellInfo
from kratos_agent.system.shell.detect import get_current_shell
from kratos_agent.utils.shell_quote import powershell_encoded, pwsh_encoded


def render_powershell_script(command: str, supports_and: bool = False) -> str:
    """Translates chained Bash/CMD syntax (&&, ||) into valid PowerShell syntax (§30, §33)."""
    clean = command.strip()

    # If the shell does not support && or || (e.g. Windows PowerShell 5.1)
    if not supports_and:
        # Replace && with '; if ($?) { ... }'
        if "&&" in clean:
            parts = clean.split("&&")
            rendered = parts[0].strip()
            for part in parts[1:]:
                rendered += f"; if ($?) {{ {part.strip()} }}"
            clean = rendered

        # Replace || with '; if (-not $?) { ... }'
        if "||" in clean:
            parts = clean.split("||")
            rendered = parts[0].strip()
            for part in parts[1:]:
                rendered += f"; if (-not $?) {{ {part.strip()} }}"
            clean = rendered

    return clean


def render_command_argv(command: str, shell: Optional[ShellInfo] = None) -> List[str]:
    """Renders command into a safe execution argv for the active shell."""
    sh = shell or get_current_shell()

    if sh.name in ("powershell", "pwsh"):
        script = render_powershell_script(command, supports_and=sh.supports_and_operator)
        if sh.name == "pwsh":
            return pwsh_encoded(script)
        return powershell_encoded(script)

    if sh.name in ("bash", "sh", "zsh"):
        return [sh.name, "-c", command]

    if sh.name in ("cmd", "cmd.exe"):
        return ["cmd.exe", "/d", "/s", "/c", command]

    return [sh.executable, "-c", command]
