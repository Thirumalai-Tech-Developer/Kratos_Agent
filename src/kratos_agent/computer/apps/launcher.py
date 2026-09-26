"""Application launcher using native OS APIs (§18, §19, §23, §35)."""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import os
import re
import subprocess
import sys
import time
from typing import Any

from kratos_agent.computer.apps.focus import (
    ensure_task_window_foreground,
    get_active_window,
)
from kratos_agent.computer.apps.windows import get_window_manager
from kratos_agent.computer.state import ActionResult

KNOWN_APPLICATIONS: dict[str, dict[str, Any]] = {
    "chrome": {
        "win": ["chrome.exe"],
        "linux": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
        "title_pattern": r"Google Chrome|Chrome",
        "name": "Google Chrome",
    },
    "vs code": {
        "win": ["code.cmd", "code.exe"],
        "linux": ["code"],
        "title_pattern": r"Visual Studio Code",
        "name": "Visual Studio Code",
    },
    "vscode": {
        "win": ["code.cmd", "code.exe"],
        "linux": ["code"],
        "title_pattern": r"Visual Studio Code",
        "name": "Visual Studio Code",
    },
    "code": {
        "win": ["code.cmd", "code.exe"],
        "linux": ["code"],
        "title_pattern": r"Visual Studio Code",
        "name": "Visual Studio Code",
    },
    "notepad": {
        "win": ["notepad.exe"],
        "linux": ["gedit", "kate", "mousepad"],
        "title_pattern": r"Notepad",
        "name": "Notepad",
    },
    "calculator": {
        "win": ["calc.exe"],
        "linux": ["gnome-calculator", "kcalc"],
        "title_pattern": r"Calculator|calc",
        "name": "Calculator",
    },
    "calc": {
        "win": ["calc.exe"],
        "linux": ["gnome-calculator", "kcalc"],
        "title_pattern": r"Calculator|calc",
        "name": "Calculator",
    },
    "whatsapp": {
        "win": ["whatsapp:", "whatsapp.exe"],
        "linux": ["whatsapp-for-linux"],
        "title_pattern": r"WhatsApp",
        "name": "WhatsApp",
    },
    "file explorer": {
        "win": ["explorer.exe"],
        "linux": ["nautilus", "dolphin", "thunar"],
        "title_pattern": r"File Explorer|Explorer",
        "name": "File Explorer",
    },
    "explorer": {
        "win": ["explorer.exe"],
        "linux": ["nautilus", "dolphin", "thunar"],
        "title_pattern": r"File Explorer|Explorer",
        "name": "File Explorer",
    },
}


class AppLauncher:
    """Launches desktop applications and processes with deterministic resolution and foreground verification (§18, §19, §35)."""

    def resolve_application(self, target: str) -> tuple[str, str, str] | None:
        """Resolves friendly application name to (executable, title_regex, display_name)."""
        clean = target.strip().lower()
        clean = re.sub(r"^(open|launch|start)\s+", "", clean).strip()
        if clean in KNOWN_APPLICATIONS:
            info = KNOWN_APPLICATIONS[clean]
            candidates = info["win"] if sys.platform == "win32" else info["linux"]
            return (candidates[0], info["title_pattern"], info["name"])

        # Prefix matching
        for k, info in KNOWN_APPLICATIONS.items():
            if clean.startswith(k) or k.startswith(clean):
                candidates = info["win"] if sys.platform == "win32" else info["linux"]
                return (candidates[0], info["title_pattern"], info["name"])

        return None

    def launch(
        self,
        target: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        elevated: bool = False,
        wait: bool = False,
        timeout: float | None = None,
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
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        # 3. Subprocess execution
        try:
            cmd = [target] + (args or [])
            p = subprocess.Popen(cmd, cwd=cwd, shell=False)

            if wait:
                ret = p.wait(timeout=timeout)
                return ActionResult(ok=(ret == 0), action="app_launch", detail=f"Exited with code {ret}", data={"returncode": ret})

            return ActionResult(ok=True, action="app_launch", detail=f"Started process pid={p.pid}", data={"pid": p.pid})
        except Exception as exc:
            return ActionResult(ok=False, action="app_launch", detail=f"Failed to launch '{target}': {exc}")

    def launch_and_verify(self, target: str, timeout: float = 6.0) -> ActionResult:
        """Deterministically resolves, launches, locates HWND, and verifies foreground ownership (§18, §35)."""
        resolved = self.resolve_application(target)
        if resolved:
            cmd, title_pat, display_name = resolved
        else:
            cmd, title_pat, display_name = target, target, target

        wm = get_window_manager()

        # Step 1: Check if already open (Prevent duplicate launch loops! §35)
        pat = re.compile(title_pat, re.IGNORECASE)
        for w in wm.list_windows():
            if pat.search(w.title or ""):
                hwnd = w.id
                print(f"[APP_LAUNCH]\nApp: {display_name}\nExisting window found: {hwnd}\nForegrounding...")
                focused = ensure_task_window_foreground(hwnd)
                return ActionResult(
                    ok=focused,
                    success=focused,
                    verified=focused,
                    terminal=True,
                    changed_state=False,
                    action="app_launch",
                    observation=f"{display_name} is already open and brought to foreground (HWND: {hwnd}).",
                    detail=f"{display_name} brought to foreground.",
                    data={"hwnd": hwnd, "app": display_name, "reused": True},
                )

        # Step 2: Launch application
        print(f"[APP_LAUNCH]\nApp: {display_name}\nCommand: {cmd}\nLaunching...")
        l_res = self.launch(cmd)
        if not l_res.ok:
            return ActionResult(
                ok=False,
                success=False,
                verified=False,
                terminal=True,
                action="app_launch",
                error=l_res.detail,
                detail=f"Failed to launch {display_name}: {l_res.detail}",
            )

        # Step 3: Locate window HWND within bounded timeout
        start_t = time.time()
        target_hwnd = None
        while time.time() - start_t < timeout:
            time.sleep(0.3)
            for w in wm.list_windows():
                if pat.search(w.title or ""):
                    target_hwnd = w.id
                    break
            if target_hwnd:
                break

        if not target_hwnd:
            # Check active window as fallback
            active = get_active_window()
            if active and pat.search(active.title or ""):
                target_hwnd = active.id

        if not target_hwnd:
            return ActionResult(
                ok=True,
                success=True,
                verified=False,
                terminal=True,
                action="app_launch",
                observation=f"{display_name} process started, but window handle could not be verified within {timeout}s.",
                detail=f"{display_name} launched (unverified window).",
                data={"app": display_name},
            )

        # Step 4: Ensure foreground and verify active HWND
        focused = ensure_task_window_foreground(target_hwnd)
        return ActionResult(
            ok=focused,
            success=focused,
            verified=focused,
            terminal=True,
            changed_state=True,
            action="app_launch",
            observation=f"{display_name} launched, window {target_hwnd} located, and foreground focus verified.",
            detail=f"{display_name} launched and focused.",
            data={"hwnd": target_hwnd, "app": display_name, "focused": focused},
        )


_launcher: AppLauncher | None = None


def get_launcher() -> AppLauncher:
    global _launcher
    if _launcher is None:
        _launcher = AppLauncher()
    return _launcher
