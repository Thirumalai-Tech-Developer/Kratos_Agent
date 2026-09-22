"""Failure classification and error types for Computer Use Engine."""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, Optional


class FailureType(str, Enum):
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    ELEMENT_DISABLED = "ELEMENT_DISABLED"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    APPLICATION_NOT_RUNNING = "APPLICATION_NOT_RUNNING"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ACTION_UNSUPPORTED = "ACTION_UNSUPPORTED"
    TIMEOUT = "TIMEOUT"
    STALE_ELEMENT = "STALE_ELEMENT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VISION_FAILED = "VISION_FAILED"
    COORDINATE_FAILED = "COORDINATE_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ComputerError(Exception):
    """Base exception for computer control operations."""
    def __init__(self, message: str, failure_type: FailureType = FailureType.UNKNOWN_ERROR, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.failure_type = failure_type
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.message,
            "failure_type": self.failure_type.value,
            "details": self.details,
        }


class TargetNotFoundError(ComputerError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, FailureType.TARGET_NOT_FOUND, details)


class AmbiguousTargetError(ComputerError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, FailureType.AMBIGUOUS_TARGET, details)


class ElementDisabledError(ComputerError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, FailureType.ELEMENT_DISABLED, details)


class StaleElementError(ComputerError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, FailureType.STALE_ELEMENT, details)


class BackendUnavailableError(ComputerError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, FailureType.BACKEND_UNAVAILABLE, details)


class VerificationFailedError(ComputerError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, FailureType.VERIFICATION_FAILED, details)
