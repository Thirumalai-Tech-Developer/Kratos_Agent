"""Cross-platform capability probing for computer control."""
from __future__ import annotations

import platform
from typing import Any


def probe_capabilities() -> dict[str, Any]:
    """Detects available subsystem capabilities on the host."""
    system = platform.system().lower()

    # 1. Accessibility
    a11y_available = False
    if system == "windows":
        try:
            from kratos_agent.computer.gui.backends.windows_uia import WindowsUIABackend
            a11y_available = WindowsUIABackend().is_available()
        except Exception:
            a11y_available = False
    elif system == "linux":
        try:
            from kratos_agent.computer.gui.backends.linux_atspi import LinuxATSPIBackend
            a11y_available = LinuxATSPIBackend().is_available()
        except Exception:
            a11y_available = False

    # 2. Browser CDP / Playwright
    browser_available = False
    try:
        from kratos_agent.computer.browser.manager import get_browser_manager
        browser_available = get_browser_manager().is_connected()
    except Exception:
        browser_available = False

    # 3. OCR / Vision
    ocr_available = False
    try:
        from kratos_agent.ccs.perception.ocr import OcrEngine
        ocr_available = OcrEngine().is_available()
    except Exception:
        ocr_available = False

    # 4. Input engines
    input_available = True

    return {
        "os": system,
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "a11y": a11y_available,
        "browser_cdp": browser_available,
        "ocr": ocr_available,
        "keyboard": input_available,
        "mouse": input_available,
        "filesystem": True,
        "clipboard": True,
    }
