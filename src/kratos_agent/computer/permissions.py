"""Privilege boundaries and safety policies for computer actions."""
from __future__ import annotations
import os
import sys
from typing import Any, Dict, Optional, Tuple

from kratos_agent.computer.state import ComputerAction


class ComputerPermissionPolicy:
    """Enforces safety boundaries on destructive or privileged actions."""

    DESTRUCTIVE_ACTIONS = {
        "file_delete",
        "process_terminate",
        "system_power",
        "system_elevate",
        "registry_delete",
        "firewall_rule",
    }

    FORBIDDEN_PATTERNS = [
        "taskkill /f /im kratos",
        "killall kratos",
        "format c:",
        "mkfs",
        "rm -rf /",
        "del /s /q c:\\windows",
    ]

    def check_permission(self, action: ComputerAction) -> Tuple[bool, str]:
        """Checks computer actions; Sovereign removes app-level permission gates."""
        try:
            from kratos_agent.core.approval_mode import approval_gate, ApprovalMode
            if approval_gate.mode is ApprovalMode.SOVEREIGN:
                approval_gate._audit.record(action.action, str(action.parameters), "ALLOW", "sovereign")
                return True, "sovereign"
        except Exception:
            pass

        # Non-Sovereign modes retain the existing policy.
        # 1. Self-preservation and system corruption checks
        params_str = str(action.parameters).lower()
        for forbidden in self.FORBIDDEN_PATTERNS:
            if forbidden in params_str:
                return False, f"Action blocked: forbidden destructive pattern detected ('{forbidden}')"

        # 2. Critical file protection
        if action.action in ("file_delete", "file_write"):
            target = str(action.parameters.get("path", "")).lower()
            if target.startswith("c:\\windows") or target.startswith("/bin") or target.startswith("/usr"):
                return False, f"Action blocked: writing or deleting in system directories is forbidden ('{target}')"

        return True, "permitted"


_permission_policy: Optional[ComputerPermissionPolicy] = None


def get_permission_policy() -> ComputerPermissionPolicy:
    global _permission_policy
    if _permission_policy is None:
        _permission_policy = ComputerPermissionPolicy()
    return _permission_policy
