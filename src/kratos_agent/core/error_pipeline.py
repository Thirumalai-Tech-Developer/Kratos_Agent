"""Global error classification, routing, and recovery pipeline for Kratos Agent (§5)."""
from __future__ import annotations

import logging
from enum import Enum

from kratos_agent.core.errors import KratosError

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    PERMISSION = "PERMISSION"
    DEVICE_MUTED = "DEVICE_MUTED"
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
    CAPTURE_FAILURE = "CAPTURE_FAILURE"
    NETWORK = "NETWORK"
    GEMINI_SESSION = "GEMINI_SESSION"
    PLAYWRIGHT = "PLAYWRIGHT"
    BROWSER_NOT_FOUND = "BROWSER_NOT_FOUND"
    PAGE_NAVIGATION = "PAGE_NAVIGATION"
    PAGE_TIMEOUT = "PAGE_TIMEOUT"
    DOM_NOT_FOUND = "DOM_NOT_FOUND"
    FOCUS_FAILURE = "FOCUS_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    CONFIGURATION = "CONFIGURATION"
    UNKNOWN = "UNKNOWN"


def classify_error(error: KratosError | Exception | str) -> ErrorCategory:
    """Classifies an error into a standardized ErrorCategory for recovery dispatch."""
    if isinstance(error, KratosError):
        msg = (error.message + " " + error.error_type + " " + error.operation).lower()
        subsystem = error.subsystem.lower()
    elif isinstance(error, Exception):
        msg = (str(error) + " " + type(error).__name__).lower()
        subsystem = ""
    else:
        msg = str(error).lower()
        subsystem = ""

    # 1. Device Mute & Availability
    if "muted" in msg:
        return ErrorCategory.DEVICE_MUTED
    if any(w in msg for w in ("device not found", "no such device", "device unavailable", "pyaudio", "sounddevice")):
        return ErrorCategory.DEVICE_UNAVAILABLE

    # 2. Permissions
    if any(w in msg for w in ("permission", "access denied", "unauthorized", "uac")):
        return ErrorCategory.PERMISSION

    # 3. Screen / Perception Capture
    if subsystem in ("screen", "vision", "perception") or any(w in msg for w in ("mss", "grab error", "screenshot", "screen capture")):
        return ErrorCategory.CAPTURE_FAILURE

    # 4. Browser / Playwright / Navigation
    if any(w in msg for w in ("playwright", "target closed", "browser disconnected")):
        return ErrorCategory.PLAYWRIGHT
    if any(w in msg for w in ("browser not found", "cannot find chrome", "chrome not found", "edge not found")):
        return ErrorCategory.BROWSER_NOT_FOUND
    if any(w in msg for w in ("err_name_not_resolved", "err_connection", "navigate", "page navigation", "goto")):
        return ErrorCategory.PAGE_NAVIGATION
    if any(w in msg for w in ("timeout", "timed out", "navigation timeout")):
        return ErrorCategory.PAGE_TIMEOUT
    if any(w in msg for w in ("selector", "element not found", "dom_not_found", "no such element")):
        return ErrorCategory.DOM_NOT_FOUND

    # 5. Window / Focus
    if any(w in msg for w in ("focus", "foreground", "setforegroundwindow", "window not found")):
        return ErrorCategory.FOCUS_FAILURE

    # 6. Verification
    if any(w in msg for w in ("verification", "unverified", "expected state not met", "not playing")):
        return ErrorCategory.VERIFICATION_FAILURE

    # 7. Gemini Live / Session
    if subsystem in ("gemini", "live", "gemini_live") or any(w in msg for w in ("getaddrinfo", "websocket", "live session", "refusal")):
        return ErrorCategory.GEMINI_SESSION

    # 8. Network
    if any(w in msg for w in ("connection refused", "network error", "dns", "http error")):
        return ErrorCategory.NETWORK

    # 9. Configuration
    if any(w in msg for w in ("api key", "config", "missing environment", "invalid argument")):
        return ErrorCategory.CONFIGURATION

    return ErrorCategory.UNKNOWN


def is_recoverable(category: ErrorCategory) -> bool:
    """Returns True if the error category can be addressed by the recovery engine."""
    unrecoverable = {
        ErrorCategory.PERMISSION,
        ErrorCategory.CONFIGURATION,
        ErrorCategory.DEVICE_MUTED,  # Requires physical/OS unmute
    }
    return category not in unrecoverable


class ErrorPipeline:
    """Central registry and dispatcher for errors occurring across Kratos."""

    def __init__(self) -> None:
        self._recent_errors: list[KratosError] = []
        self._max_history = 50

    def record_error(self, error: KratosError) -> ErrorCategory:
        """Records a structured error and returns its classification."""
        category = classify_error(error)
        error.recoverable = is_recoverable(category)
        error.details["category"] = category.value

        self._recent_errors.append(error)
        if len(self._recent_errors) > self._max_history:
            self._recent_errors.pop(0)

        logger.warning(f"[ErrorPipeline] {category.value} in {error.subsystem}:{error.operation} - {error.message}")
        return category

    def process_error(self, error: KratosError) -> KratosError:
        """Processes a structured error, assigns classification and recovery status, and returns the error (§5)."""
        category = self.record_error(error)
        error.details["category"] = category.value
        return error


    def get_recent_errors(self, subsystem: str | None = None) -> list[KratosError]:
        if subsystem:
            return [e for e in self._recent_errors if e.subsystem.lower() == subsystem.lower()]
        return list(self._recent_errors)

    def clear(self) -> None:
        self._recent_errors.clear()


_global_error_pipeline: ErrorPipeline | None = None


def get_error_pipeline() -> ErrorPipeline:
    global _global_error_pipeline
    if _global_error_pipeline is None:
        _global_error_pipeline = ErrorPipeline()
    return _global_error_pipeline
