"""Browser automation and CDP-based media inspection tools.
"""
from __future__ import annotations
import json
import re
import sys
import time
from typing import Any, Dict, Optional
from kratos_agent.ccs.base import ActionResult
from kratos_agent.core.evidence import OutcomeAssertion
from kratos_agent.utils.shell_quote import youtube_search_url, build_url
from .cdp import cdp_client

def browser_open(url: str, browser: str = "chrome", profile: str = "Default") -> ActionResult:
    """Opens a URL in the browser without shell interpolation, returning the needed assertion."""
    # Ensure scheme
    if not re.match(r"^[a-zA-Z]+://", url):
        url = "https://" + url

    # Try CDP navigate if already attached
    if cdp_client.is_available() and cdp_client.navigate(url):
        return ActionResult(
            ok=True,
            action="browser_open",
            data={"url": url, "via": "cdp"},
            needs_assertion=OutcomeAssertion(
                kind="url_matches",
                params={"pattern": re.escape(url.split("//")[-1].split("?")[0])},
                timeout_s=15.0,
            ),
        )

    # Launch browser via OS process
    import subprocess
    import os
    if sys.platform == "win32":
        try:
            os.startfile(url)
        except Exception:
            subprocess.Popen(["chrome.exe", url], shell=False)
    else:
        subprocess.Popen(["google-chrome", url], shell=False)

    return ActionResult(
        ok=True,
        action="browser_open",
        data={"url": url, "via": "os_launch"},
        needs_assertion=OutcomeAssertion(
            kind="composite",
            params={
                "all_of": [
                    {"kind": "process_running", "params": {"name": "chrome.exe" if sys.platform == "win32" else "chrome"}},
                    {"kind": "url_matches", "params": {"pattern": re.escape(url.split("//")[-1].split("?")[0])}},
                ]
            },
            timeout_s=15.0,
        ),
    )


def browser_js(script: str) -> Dict[str, Any]:
    """Evaluates JavaScript via CDP and returns structured JSON."""
    if not cdp_client.is_available():
        return {"ok": False, "error": "CDP not available"}
    val = cdp_client.evaluate(script)
    return {"ok": True, "value": val}


def browser_click(selector: str) -> ActionResult:
    """Clicks an element in the browser via CDP."""
    if not cdp_client.is_available():
        return ActionResult(ok=False, action="browser_click", detail="CDP not available")
    success = cdp_client.click(selector)
    return ActionResult(ok=success, action="browser_click", data={"selector": selector})


def media_probe(selector: str = "video", samples: int = 2, gap_ms: int = 1500) -> Dict[str, Any]:
    """Probes video playback state via CDP, sampling multiple times to confirm advancing time."""
    if not cdp_client.is_available():
        return {"ok": False, "error": "CDP not available"}

    s1 = cdp_client.get_video_state(selector)
    if not s1.get("found"):
        return {"ok": False, "error": f"No element matching '{selector}' found"}

    if samples <= 1:
        return {"ok": True, "samples": [s1], "advancing": False}

    time.sleep(gap_ms / 1000.0)
    s2 = cdp_client.get_video_state(selector)
    t1 = s1.get("currentTime", 0.0)
    t2 = s2.get("currentTime", 0.0)
    advancing = (t2 - t1) >= 0.3 and not s2.get("paused", True)

    return {
        "ok": True,
        "samples": [s1, s2],
        "delta_s": round(t2 - t1, 2),
        "advancing": advancing,
        "paused": s2.get("paused", True),
    }


def media_control_verify(action: str, value: Any = None, selector: str = "video") -> ActionResult:
    """Controls media playback and immediately verifies state via media_probe."""
    if not cdp_client.is_available():
        return ActionResult(ok=False, action="media_control_verify", detail="CDP not available")

    if action == "play":
        cdp_client.evaluate(f"document.querySelector('{selector}') ? document.querySelector('{selector}').play() : null")
    elif action == "pause":
        cdp_client.evaluate(f"document.querySelector('{selector}') ? document.querySelector('{selector}').pause() : null")
    elif action == "seek" and value is not None:
        cdp_client.evaluate(f"document.querySelector('{selector}') ? document.querySelector('{selector}').currentTime = {float(value)} : null")
    elif action == "volume" and value is not None:
        cdp_client.evaluate(f"document.querySelector('{selector}') ? document.querySelector('{selector}').volume = {float(value)} : null")

    probe = media_probe(selector=selector, samples=2, gap_ms=800)
    is_met = probe.get("advancing", False) if action == "play" else (probe.get("paused", False) if action == "pause" else True)

    return ActionResult(
        ok=is_met,
        action="media_control_verify",
        data={"action": action, "probe": probe},
        needs_assertion=OutcomeAssertion(
            kind="media_playing" if action == "play" else "media_paused",
            params={"selector": selector},
            require_samples=2,
            sample_gap_ms=1000,
        ),
    )
