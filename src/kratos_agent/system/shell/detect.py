"""Operating-system shell detection and capability discovery."""
from __future__ import annotations
import shutil
import sys
from typing import Optional

from kratos_agent.system.shell.base import ShellInfo


def detect_shell() -> ShellInfo:
    """Detects active system shell and operator support (§28)."""
    if sys.platform == "win32":
        # Check if PowerShell 7+ (pwsh) is installed
        pwsh_path = shutil.which("pwsh.exe") or shutil.which("pwsh")
        if pwsh_path:
            return ShellInfo(
                name="pwsh",
                version="7+",
                platform="windows",
                executable=pwsh_path,
                supports_and_operator=True,
                supports_or_operator=True,
            )

        # Default Windows PowerShell (5.1)
        ps_path = shutil.which("powershell.exe") or "powershell.exe"
        return ShellInfo(
            name="powershell",
            version="5.1",
            platform="windows",
            executable=ps_path,
            supports_and_operator=False,  # && not supported in PS 5.1!
            supports_or_operator=False,   # || not supported in PS 5.1!
        )

    # POSIX systems (Linux / macOS)
    bash_path = shutil.which("bash")
    if bash_path:
        return ShellInfo(
            name="bash",
            version=None,
            platform=sys.platform,
            executable=bash_path,
            supports_and_operator=True,
            supports_or_operator=True,
        )

    sh_path = shutil.which("sh") or "/bin/sh"
    return ShellInfo(
        name="sh",
        version=None,
        platform=sys.platform,
        executable=sh_path,
        supports_and_operator=True,
        supports_or_operator=True,
    )


_current_shell: Optional[ShellInfo] = None


def get_current_shell() -> ShellInfo:
    global _current_shell
    if _current_shell is None:
        _current_shell = detect_shell()
    return _current_shell
