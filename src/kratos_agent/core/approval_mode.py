"""
Approval/Permission Mode system for Kratos Agent.
Mirrors Codex CLI (suggest / auto-edit / full-auto) and Kimi Code safe mode.

Modes:
  SUGGEST    — Agent can read/analyze only. All writes/execs need user approval.
  AUTO_EDIT  — Agent can edit files freely. Shell commands need user approval.
  FULL_AUTO  — Agent has full autonomy (current Kratos default).

Additionally enforces a SAFE blocklist of destructive shell patterns regardless of mode.
"""
from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

console = Console(highlight=False)

# ──────────────────────────────────────────────────────────
# Destructive command blocklist (Codex-style safety)
# ──────────────────────────────────────────────────────────
_DANGEROUS_PATTERNS = [
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+/",        # rm -rf /
    r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r?\s+/",        # rm -fr /
    r"\bdel\s+/[sS]\s+[cC]:\\",                   # del /s C:\
    r"\bformat\s+[a-zA-Z]:",                       # format C:
    r"\bdiskpart\b",                               # diskpart
    r"\bdd\s+if=.*of=/dev/[sh]d",                 # dd overwrite disk
    r"DROP\s+(?:TABLE|DATABASE|SCHEMA)\s+\w+",    # SQL drops
    r"\bsudo\s+rm\s+-[a-zA-Z]*r[a-zA-Z]*f",       # sudo rm -rf
    r">\s*/dev/[sh]d[a-z]",                        # redirect to disk device
    r"\bshutdown\b.*-[rft]",                       # shutdown command
    r"\bmkfs\.",                                   # mkfs format disk
]
_COMPILED_DANGEROUS = [re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS]


def is_dangerous_command(command: str) -> bool:
    """Returns True if a shell command matches any known destructive pattern."""
    return any(p.search(command) for p in _COMPILED_DANGEROUS)


# ──────────────────────────────────────────────────────────
# Approval Mode Enum
# ──────────────────────────────────────────────────────────
class ApprovalMode(str, Enum):
    SUGGEST   = "suggest"     # Read only, all mutations need approval
    AUTO_EDIT = "auto-edit"   # Files auto, shell needs approval
    FULL_AUTO = "full-auto"   # Full autonomy (default)


class ApprovalGate:
    """
    Central permission gate wrapping tool calls.
    Loaded from / saved to .kratos/settings.json.
    """

    SETTINGS_FILE = Path(".kratos/settings.json")

    def __init__(self):
        self._mode = ApprovalMode.FULL_AUTO
        self._load()

    def _load(self):
        try:
            if self.SETTINGS_FILE.exists():
                data = json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
                mode_val = data.get("approval_mode", "full-auto")
                self._mode = ApprovalMode(mode_val)
        except Exception:
            self._mode = ApprovalMode.FULL_AUTO

    def _save(self):
        try:
            self.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if self.SETTINGS_FILE.exists():
                try:
                    data = json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    pass
            data["approval_mode"] = self._mode.value
            self.SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @property
    def mode(self) -> ApprovalMode:
        return self._mode

    def set_mode(self, mode: ApprovalMode):
        self._mode = mode
        self._save()
        mode_colors = {
            ApprovalMode.SUGGEST:   "[yellow]",
            ApprovalMode.AUTO_EDIT: "[cyan]",
            ApprovalMode.FULL_AUTO: "[green]",
        }
        color = mode_colors.get(mode, "[white]")
        console.print(f"[bold]Approval mode set to {color}{mode.value}[/]")

    def check_shell(self, command: str) -> bool:
        """
        Returns True if the shell command is allowed to proceed.
        Always blocks dangerous commands.
        In SUGGEST or AUTO_EDIT mode, prompts user before executing.
        """
        # Safety blocklist — always enforced
        if is_dangerous_command(command):
            console.print(
                f"\n[bold red]⛔ BLOCKED (dangerous command):[/bold red] [yellow]{command}[/yellow]\n"
                "This matches a destructive pattern and will never be executed."
            )
            return False

        if self._mode == ApprovalMode.FULL_AUTO:
            return True

        if self._mode in (ApprovalMode.SUGGEST, ApprovalMode.AUTO_EDIT):
            console.print(f"\n[bold yellow]⚡ Shell command requires approval ({self._mode.value} mode):[/bold yellow]")
            console.print(f"[cyan]{command}[/cyan]")
            answer = Prompt.ask("Allow? [y/N]", default="n")
            return answer.strip().lower() in ("y", "yes")

        return True

    def check_write(self, file_path: str) -> bool:
        """
        Returns True if the file write is allowed.
        Blocked in SUGGEST mode (read-only).
        """
        if self._mode == ApprovalMode.SUGGEST:
            console.print(
                f"\n[bold yellow]✋ File write blocked (suggest mode):[/bold yellow] [cyan]{file_path}[/cyan]\n"
                "Switch to auto-edit or full-auto mode to allow writes: [bold]/mode auto-edit[/bold]"
            )
            return False
        return True

    def mode_badge(self) -> str:
        """Returns a compact colored badge for the CLI prompt."""
        badges = {
            ApprovalMode.SUGGEST:   "[yellow]●SUGGEST[/yellow]",
            ApprovalMode.AUTO_EDIT: "[cyan]●AUTO-EDIT[/cyan]",
            ApprovalMode.FULL_AUTO: "[green]●FULL-AUTO[/green]",
        }
        return badges.get(self._mode, "")


# Global singleton
approval_gate = ApprovalGate()
