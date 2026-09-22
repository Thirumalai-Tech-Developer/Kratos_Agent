"""Foreground window focus policies for desktop and browser operations (§8, §25, §26)."""
from __future__ import annotations

from enum import Enum


class FocusPolicy(str, Enum):
    KEEP_CURRENT = "keep_current"
    FOCUS_TARGET = "focus_target"
    RESTORE_PREVIOUS = "restore_previous"
