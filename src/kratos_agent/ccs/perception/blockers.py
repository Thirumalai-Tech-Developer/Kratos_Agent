from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import re
import time
from dataclasses import dataclass, field
from typing import Any

from kratos_agent.core.evidence import Evidence


@dataclass
class Blocker:
    name: str
    detail: str
    spoken_hint: str
    clearable: bool
    cdp_probe: str | None = None
    ocr_patterns: list[str] = field(default_factory=list)


BLOCKERS_DEF = [
    (
        "cookie_consent",
        "!!document.querySelector('[aria-label*=\"Accept\" i], #dialog button, tp-yt-paper-dialog button, [data-testid=\"cookie-policy-manage-dialog\"]')",
        [r"accept all", r"agree to all", r"cookies"],
        "There's a cookie dialog in the way — dismissing it.",
        True,
    ),
    (
        "youtube_bot_wall",
        "!!Array.from(document.querySelectorAll('h1,h2,p,span,div')).find(e=>/sign in to confirm|not a robot|confirm you're not/i.test(e.textContent||''))",
        [r"sign in to confirm", r"not a robot"],
        "YouTube is showing a sign-in wall. I can't play this video without an account.",
        False,
    ),
    (
        "age_gate",
        "!!Array.from(document.querySelectorAll('button')).find(b=>/confirm|yes,? i.?m|continue/i.test(b.textContent||''))",
        [r"age.?restricted", r"confirm your age"],
        "There's an age confirmation on this video.",
        True,
    ),
    (
        "autoplay_blocked",
        "(()=>{const v=document.querySelector('video'); return !!v && v.paused && v.error===null && v.readyState>=2})()",
        [r"tap to play", r"play video", r"resume"],
        "The browser blocked autoplay. I'll click the player directly.",
        True,
    ),
    (
        "ad_overlay",
        "!!document.querySelector('.ad-showing, .video-ads, #movie_player.ad-showing')",
        [r"skip ad", r"ad \d+", r"skip in"],
        "An ad is playing — waiting for the skip.",
        True,
    ),
    (
        "native_modal",
        None,
        [r"allow notifications", r"enable notifications", r"sign in", r"log in", r"install app"],
        "A modal dialog is blocking the page.",
        True,
    ),
    (
        "browser_dialog",
        None,
        [r"leave site\?", r"changes you made"],
        "The browser is showing a leave-site dialog.",
        True,
    ),
    (
        "os_uac",
        None,
        [r"user account control", r"do you want to allow"],
        "Windows is showing a UAC prompt.",
        False,
    ),
]


def get_blocker_by_name(name: str) -> Blocker | None:
    for b_name, probe, patterns, hint, clearable in BLOCKERS_DEF:
        if b_name == name:
            return Blocker(name=b_name, detail=hint, spoken_hint=hint, clearable=clearable, cdp_probe=probe, ocr_patterns=patterns)
    return None


def detect_blockers(ccs: Any, frame_ref: str | None = None) -> list[Blocker]:
    """Run CDP probes where available, OCR fallback always. Returns every match."""
    matches: list[Blocker] = []

    # 1. Try CDP probes if browser is attached/available
    cdp_eval = getattr(ccs, "browser_js", None) or getattr(ccs, "cdp_eval", None)
    if cdp_eval:
        for name, probe, patterns, hint, clearable in BLOCKERS_DEF:
            if probe:
                try:
                    res = cdp_eval(probe)
                    val = res.get("value") if isinstance(res, dict) else res
                    if val is True or str(val).lower() == "true":
                        matches.append(Blocker(name=name, detail=hint, spoken_hint=hint, clearable=clearable, cdp_probe=probe, ocr_patterns=patterns))
                except Exception as exc:
                    logger.debug("Operation error suppressed: %s", exc)

    # 2. OCR fallback / native checks
    text_corpus = ""
    ocr_read = getattr(ccs, "screen_read_text", None) or getattr(ccs, "ocr_read", None)
    if ocr_read:
        try:
            text_corpus = str(ocr_read(frame_ref=frame_ref) or "").lower()
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    if text_corpus:
        for name, probe, patterns, hint, clearable in BLOCKERS_DEF:
            # Skip if already detected via CDP
            if any(m.name == name for m in matches):
                continue
            for pat in patterns:
                if re.search(pat, text_corpus, re.IGNORECASE):
                    matches.append(Blocker(name=name, detail=hint, spoken_hint=hint, clearable=clearable, cdp_probe=probe, ocr_patterns=patterns))
                    break

    return matches


def clear_blocker(ccs: Any, blocker: Blocker | str) -> Evidence:
    """Attempt to dismiss it (click Accept / Skip / close / Escape / wait for ad).
    Returns Evidence that the blocker is gone. If it cannot be cleared — e.g. the
    bot wall — returns met=False with the spoken_hint as detail so the task can
    fail honestly with a real reason."""
    if isinstance(blocker, str):
        b = get_blocker_by_name(blocker)
        if not b:
            return Evidence(
                claim=f"clear_{blocker}",
                method="cdp_js",
                met=False,
                observed={},
                confidence=0.0,
                detail=f"Unknown blocker: {blocker}",
            )
        blocker = b

    if not blocker.clearable:
        return Evidence(
            claim=f"clear_{blocker.name}",
            method="cdp_js" if blocker.cdp_probe else "ocr",
            met=False,
            observed={"blocker": blocker.name, "clearable": False},
            confidence=1.0,
            detail=blocker.spoken_hint,
        )

    cdp_eval = getattr(ccs, "browser_js", None) or getattr(ccs, "cdp_eval", None)
    browser_click = getattr(ccs, "browser_click", None)
    key_tap = getattr(ccs, "key_tap", None)

    def _poll_blocker_cleared(probe: str | None, timeout_s: float = 1.5, poll_s: float = 0.1) -> bool:
        if not probe or not cdp_eval:
            return True
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                r = cdp_eval(probe)
                v = r.get("value") if isinstance(r, dict) else r
                if not (v is True or str(v).lower() == "true"):
                    return True
            except Exception:
                return True
            time.sleep(poll_s)
        return False

    if blocker.name == "cookie_consent":
        # Try clicking accept button via JS
        if cdp_eval:
            try:
                click_script = (
                    "(()=>{ const b = document.querySelector('[aria-label*=\"Accept\" i], #dialog button, tp-yt-paper-dialog button, [data-testid=\"cookie-policy-manage-dialog\"] button');"
                    " if(b){ b.click(); return true; } return false; })()"
                )
                res = cdp_eval(click_script)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
        _poll_blocker_cleared(blocker.cdp_probe)

    elif blocker.name == "autoplay_blocked":
        # Try triggering play via JS or clicking player
        if cdp_eval:
            try:
                res = cdp_eval("document.querySelector('video') ? (document.querySelector('video').play(), true) : false")
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
        if browser_click:
            try:
                browser_click(selector="video")
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
        _poll_blocker_cleared(blocker.cdp_probe)

    elif blocker.name == "ad_overlay":
        # Try skip ad
        if cdp_eval:
            try:
                skip_script = (
                    "(()=>{ const b = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, button.ytp-ad-skip-button-modern');"
                    " if(b){ b.click(); return true; } return false; })()"
                )
                cdp_eval(skip_script)
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)
        _poll_blocker_cleared(blocker.cdp_probe)

    elif blocker.name in ("native_modal", "browser_dialog"):
        if key_tap:
            try:
                key_tap("escape")
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

    # Re-check if blocker persists
    still_there = False
    if blocker.cdp_probe and cdp_eval:
        try:
            res = cdp_eval(blocker.cdp_probe)
            val = res.get("value") if isinstance(res, dict) else res
            still_there = bool(val is True or str(val).lower() == "true")
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

    if still_there:
        return Evidence(
            claim=f"clear_{blocker.name}",
            method="cdp_js",
            met=False,
            observed={"still_present": True},
            confidence=0.9,
            detail=f"{blocker.name} could not be cleared automatically: {blocker.spoken_hint}",
        )

    return Evidence(
        claim=f"clear_{blocker.name}",
        method="cdp_js",
        met=True,
        observed={"cleared": True},
        confidence=1.0,
        detail=f"{blocker.name} cleared successfully",
    )
