"""Shell data models and command execution contracts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShellInfo:
    """Represents detected shell capabilities (§28)."""
    name: str
    version: str | None
    platform: str
    executable: str
    supports_and_operator: bool
    supports_or_operator: bool


@dataclass
class CommandResult:
    """Normalized command execution output (§34, §36)."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    error_type: str | None = None

    def to_output(self) -> str:
        """Returns clean text output for user or agent."""
        if self.success:
            return self.stdout.strip()
        err = self.stderr.strip() or self.stdout.strip()
        return f"Command failed (Exit code: {self.exit_code}):\n{err}"
