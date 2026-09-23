from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class BrowserReadiness:
    ready: bool
    reason: str = ""


def wait_until_ready(probe: Callable[[], bool], timeout: float = 15.0, interval: float = 0.25) -> BrowserReadiness:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            if probe():
                return BrowserReadiness(True)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(interval)
    return BrowserReadiness(False, last_error or "readiness probe timed out")
