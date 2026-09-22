"""Application launcher using native OS APIs."""
from __future__ import annotations
import os
import sys
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional

from kratos_agent.computer.state import ActionResult


class AppLauncher:
    """Launches desktop applications and processes using native OS APIs."""

    def launch(
        self,
        target: str,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        elevated: bool = False,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> ActionResult:
        """Launches target executable, shortcut, or URI."""
        # 1. Elevated launch if requested
        if elevated:
            if sys.platform == "win32":
                from kratos_agent.utils.shell_quote import argv_for
                cmd_str = f"{target} {' '.join(args or [])}"
                argv = argv_for("powershell", f"Start-Process '{target}' -Verb RunAs -ArgumentList '{' '.join(args or [])}'")
                subprocess.Popen(argv, shell=False)
                return ActionResult(ok=True, action="app_launch", detail=f"Launched elevated: {target}", data={"elevated": True})

        # 2. Windows shell launch (e.g. 'notepad', 'calc', 'chrome', or a file path)
        if sys.platform == "win32" and not args:
            try:
                os.startfile(target)
                return ActionResult(ok=True, action="app_launch", detail=f"Launched via os.startfile: {target}")
            except Exception:
                pass

        # 3. Subprocess execution
        try:
            cmd = [target] + (args or [])
            if sys.platform == "win32":
                # Check PATH or common executable extensions
                p = subprocess.Popen(cmd, cwd=cwd, shell=False)
            else:
                p = subprocess.Popen(cmd, cwd=cwd, shell=False)

            if wait:
                ret = p.wait(timeout=timeout)
                return ActionResult(ok=(ret == 0), action="app_launch", detail=f"Exited with code {ret}", data={"returncode": ret})

            return ActionResult(ok=True, action="app_launch", detail=f"Started process pid={p.pid}", data={"pid": p.pid})
        except Exception as exc:
            return ActionResult(ok=False, action="app_launch", detail=f"Failed to launch '{target}': {exc}")


_launcher: Optional[AppLauncher] = None


def get_launcher() -> AppLauncher:
    global _launcher
    if _launcher is None:
        _launcher = AppLauncher()
    return _launcher
