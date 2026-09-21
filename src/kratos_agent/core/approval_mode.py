"""
Approval/Permission Mode system for Kratos Agent.
Mirrors Codex CLI (suggest / auto-edit / full-auto) and Kimi Code safe mode.

Modes:
  SUGGEST    — Agent can read/analyze only. All writes/execs need user approval.
  AUTO_EDIT  — Agent can edit files freely. Shell commands need user approval.
  FULL_AUTO  — Agent has full autonomy.
  SOVEREIGN  — No limitations. Full authority. Default for Jarvis.
"""
from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from dataclasses import dataclass

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
# Approval Mode Enum & Capabilities
# ──────────────────────────────────────────────────────────
class ApprovalMode(str, Enum):
    SUGGEST   = "suggest"     # Read only, all mutations need approval
    AUTO_EDIT = "auto-edit"   # Files auto, shell needs approval
    FULL_AUTO = "full-auto"   # Full autonomy
    SOVEREIGN = "sovereign"   # Jarvis authority

@dataclass
class Decision:
    allow: bool
    needs_confirmation: bool
    reason: str

class AuditLogger:
    def record(self, capability: str, target: str | None, decision: str, mode: str):
        try:
            from kratos_agent.ccs.safety_ops import safety
            safety.record_audit(capability, target, decision, mode)
        except Exception:
            pass

class ApprovalGate:
    """
    Central permission gate wrapping tool calls.
    Loaded from / saved to .kratos/settings.json.
    """

    SETTINGS_FILE = Path(".kratos/settings.json")

    def __init__(self):
        self._mode = ApprovalMode.SOVEREIGN # Set default to Sovereign
        self._audit = AuditLogger()
        self._load()

    def _load(self):
        try:
            if self.SETTINGS_FILE.exists():
                data = json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
                mode_val = data.get("approval_mode", "sovereign")
                self._mode = ApprovalMode(mode_val)
        except Exception:
            self._mode = ApprovalMode.SOVEREIGN

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
            ApprovalMode.SOVEREIGN: "[bold magenta]",
        }
        color = mode_colors.get(mode, "[white]")
        console.print(f"[bold]Approval mode set to {color}{mode.value}[/]")

    def resolve(self, capability: str, target: str | None = None) -> Decision:
        if self._mode is ApprovalMode.SOVEREIGN:
            # Jarvis authority. No human in the loop. Audit only.
            self._audit.record(capability=capability, target=target, decision="ALLOW", mode="sovereign")
            return Decision(allow=True, needs_confirmation=False, reason="sovereign")

        # Fallbacks for other modes based on basic string matching on capability
        if capability in ("read", "network", "display", "gui_read"):
            return Decision(allow=True, needs_confirmation=False, reason=self._mode.value)

        if self._mode == ApprovalMode.FULL_AUTO:
            return Decision(allow=True, needs_confirmation=False, reason=self._mode.value)

        if self._mode == ApprovalMode.AUTO_EDIT and capability in ("write", "git"):
            return Decision(allow=True, needs_confirmation=False, reason="auto-edit allows writes")

        # SUGGEST or destructive/shell in AUTO_EDIT needs confirmation
        return Decision(allow=False, needs_confirmation=True, reason=f"requires approval in {self._mode.value} mode")

    def check_shell(self, command: str) -> bool:
        """Legacy helper for simple string checks. Used by standard Kratos tools."""
        if is_dangerous_command(command):
            console.print(
                f"\n[bold red]⛔ BLOCKED (dangerous command):[/bold red] [yellow]{command}[/yellow]\n"
                "This matches a destructive pattern and will never be executed."
            )
            return False

        decision = self.resolve("execute", command)
        if decision.allow and not decision.needs_confirmation:
            return True

        if decision.needs_confirmation:
            console.print(f"\n[bold yellow]⚡ Shell command requires approval ({self._mode.value} mode):[/bold yellow]")
            console.print(f"[cyan]{command}[/cyan]")
            answer = Prompt.ask("Allow? [y/N]", default="n")
            return answer.strip().lower() in ("y", "yes")

        return False

    def check_write(self, file_path: str) -> bool:
        """Legacy helper for file writes."""
        decision = self.resolve("write", file_path)
        if decision.allow and not decision.needs_confirmation:
            return True

        if decision.needs_confirmation and self._mode == ApprovalMode.SUGGEST:
            console.print(
                f"\n[bold yellow]✋ File write blocked (suggest mode):[/bold yellow] [cyan]{file_path}[/cyan]\n"
                "Switch to auto-edit or full-auto mode to allow writes: [bold]/mode auto-edit[/bold]"
            )
            return False
            
        return decision.allow

    def mode_badge(self) -> str:
        """Returns a compact colored badge for the CLI prompt."""
        badges = {
            ApprovalMode.SUGGEST:   "[yellow]●SUGGEST[/yellow]",
            ApprovalMode.AUTO_EDIT: "[cyan]●AUTO-EDIT[/cyan]",
            ApprovalMode.FULL_AUTO: "[green]●FULL-AUTO[/green]",
            ApprovalMode.SOVEREIGN: "[bold magenta]⚡ SOVEREIGN[/bold magenta]",
        }
        return badges.get(self._mode, "")

# Global singleton
approval_gate = ApprovalGate()
