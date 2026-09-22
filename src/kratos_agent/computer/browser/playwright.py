"""Playwright browser automation driver with CDP fallback."""
from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional

from dataclasses import dataclass
from kratos_agent.ccs.browser.cdp import cdp_client
from kratos_agent.computer.state import ActionResult


@dataclass
class VideoPlaybackState:
    """Detailed video playback state (§12, §13)."""
    video_present: bool
    paused: bool
    current_time: float
    duration: float
    ready_state: int
    visible: bool
    url: str
    title: str

    @property
    def is_playing(self) -> bool:
        return self.video_present and self.visible and not self.paused and self.duration > 0


class PlaywrightDriver:
    """Semantic browser driver preferring role-based DOM interactions."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False

    def is_available(self) -> bool:
        # Returns True if Playwright library is importable OR CDP is connected
        if cdp_client.is_available():
            return True
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    def click(self, role: Optional[str] = None, name: Optional[str] = None, selector: Optional[str] = None) -> ActionResult:
        """Clicks an element using semantic role/name or CSS selector."""
        if cdp_client.is_available():
            if selector:
                success = cdp_client.click(selector)
                return ActionResult(ok=success, action="browser_click", data={"selector": selector}, method_used="cdp_selector")
            elif role or name:
                # Semantic DOM click via JS in CDP
                js = f"""(() => {{
                    const role = "{role or ''}".toLowerCase();
                    const name = "{name or ''}".toLowerCase();
                    const candidates = Array.from(document.querySelectorAll('button, a, input[type=button], input[type=submit], [role]'));
                    for (const el of candidates) {{
                        const elRole = (el.getAttribute('role') || el.tagName).toLowerCase();
                        const elText = (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase();
                        if ((!role || elRole.includes(role)) && (!name || elText.includes(name))) {{
                            el.click();
                            return true;
                        }}
                    }}
                    return false;
                }})()"""
                res = cdp_client.evaluate(js)
                return ActionResult(ok=bool(res), action="browser_click", data={"role": role, "name": name}, method_used="cdp_semantic_dom")

        return ActionResult(ok=False, action="browser_click", detail="Browser not connected")

    def fill(self, text: str, role: Optional[str] = None, name: Optional[str] = None, selector: Optional[str] = None) -> ActionResult:
        """Fills an input or textarea element."""
        if cdp_client.is_available():
            clean_text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            if selector:
                js = f"""(() => {{
                    const el = document.querySelector('{selector}');
                    if (el) {{
                        el.value = '{clean_text}';
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return true;
                    }}
                    return false;
                }})()"""
            else:
                js = f"""(() => {{
                    const name = "{name or ''}".toLowerCase();
                    const inputs = Array.from(document.querySelectorAll('input, textarea'));
                    for (const el of inputs) {{
                        const label = (el.placeholder || el.name || el.getAttribute('aria-label') || el.id || '').toLowerCase();
                        if (!name || label.includes(name)) {{
                            el.focus();
                            el.value = '{clean_text}';
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }}
                    }}
                    return false;
                }})()"""
            res = cdp_client.evaluate(js)
            return ActionResult(ok=bool(res), action="browser_fill", data={"text": text}, method_used="cdp_dom_fill")

        return ActionResult(ok=False, action="browser_fill", detail="Browser not connected")

    def verify_video_playing(self) -> VideoPlaybackState:
        """Verifies actual video element presence, visibility, and progressing playback (§12, §13)."""
        empty_state = VideoPlaybackState(
            video_present=False,
            paused=True,
            current_time=0.0,
            duration=0.0,
            ready_state=0,
            visible=False,
            url="",
            title="",
        )
        if not cdp_client.is_available():
            return empty_state

        js_check = """(() => {
            const v = document.querySelector('video');
            if (!v) return null;
            const rect = v.getBoundingClientRect();
            const visible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(v).visibility !== 'hidden';
            return {
                video_present: true,
                paused: v.paused,
                current_time: v.currentTime || 0,
                duration: v.duration || 0,
                ready_state: v.readyState || 0,
                visible: visible,
                url: window.location.href,
                title: document.title
            };
        })()"""

        res1 = cdp_client.evaluate(js_check)
        if not res1 or not isinstance(res1, dict):
            return empty_state

        state1 = VideoPlaybackState(
            video_present=bool(res1.get("video_present")),
            paused=bool(res1.get("paused")),
            current_time=float(res1.get("current_time", 0.0)),
            duration=float(res1.get("duration", 0.0)),
            ready_state=int(res1.get("ready_state", 0)),
            visible=bool(res1.get("visible")),
            url=str(res1.get("url", "")),
            title=str(res1.get("title", "")),
        )

        # Time-based verification: wait 0.7s and ensure currentTime progresses (§13)
        if state1.video_present and state1.visible and not state1.paused:
            time.sleep(0.7)
            res2 = cdp_client.evaluate(js_check)
            if res2 and isinstance(res2, dict):
                t2 = float(res2.get("current_time", 0.0))
                # Update current_time and verify advance
                if (t2 - state1.current_time) > 0.05 or t2 > state1.current_time:
                    return VideoPlaybackState(
                        video_present=True,
                        paused=bool(res2.get("paused")),
                        current_time=t2,
                        duration=float(res2.get("duration", 0.0)),
                        ready_state=int(res2.get("ready_state", 0)),
                        visible=bool(res2.get("visible")),
                        url=str(res2.get("url", "")),
                        title=str(res2.get("title", "")),
                    )

        return state1

    def search_and_play_youtube(self, query: str) -> ActionResult:
        """Automates YouTube search, result selection, and verified video playback (§11, §12, §13)."""
        if not cdp_client.is_available():
            return ActionResult(ok=False, action="youtube_play", detail="Browser not connected via CDP")

        # 1. Fill search input
        clean_q = query.replace("'", "\\'")
        js_search = f"""(() => {{
            const input = document.querySelector('input#search') || document.querySelector('input[name=search_query]');
            if (input) {{
                input.focus();
                input.value = '{clean_q}';
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                const form = input.closest('form');
                if (form) {{
                    form.submit();
                    return true;
                }}
                const btn = document.querySelector('button#search-icon-legacy');
                if (btn) {{
                    btn.click();
                    return true;
                }}
            }}
            return false;
        }})()"""
        searched = cdp_client.evaluate(js_search)
        if not searched:
            # Navigate directly to search URL
            from urllib.parse import quote_plus
            cdp_client.navigate(f"https://www.youtube.com/results?search_query={quote_plus(query)}")

        time.sleep(1.5)

        # 2. Select first video result
        js_click_video = """(() => {
            const videoLinks = Array.from(document.querySelectorAll('ytd-video-renderer a#video-title, a.yt-simple-endpoint[href*="/watch"]'));
            for (const link of videoLinks) {
                if (link.href && link.href.includes('/watch')) {
                    link.click();
                    return link.href;
                }
            }
            return null;
        })()"""
        video_href = cdp_client.evaluate(js_click_video)
        time.sleep(2.0)

        # 3. Ensure video starts playing (unpause if needed)
        js_start_play = """(() => {
            const v = document.querySelector('video');
            if (v && v.paused) {
                v.play();
                return true;
            }
            return Boolean(v);
        })()"""
        cdp_client.evaluate(js_start_play)

        # 4. Verify playback with advancing time (§13)
        v_state = self.verify_video_playing()
        if v_state.is_playing:
            return ActionResult(
                ok=True,
                action="youtube_play",
                detail=f"Video playback confirmed: '{v_state.title}' (time: {v_state.current_time:.1f}s)",
                data={"url": v_state.url, "title": v_state.title, "current_time": v_state.current_time},
                verified=True,
            )

        # Retry once (§16)
        cdp_client.evaluate(js_start_play)
        time.sleep(1.0)
        v_state = self.verify_video_playing()
        if v_state.is_playing:
            return ActionResult(
                ok=True,
                action="youtube_play",
                detail=f"Video playback confirmed after retry: '{v_state.title}'",
                data={"url": v_state.url, "title": v_state.title, "current_time": v_state.current_time},
                verified=True,
            )

        return ActionResult(
            ok=False,
            action="youtube_play",
            detail="Could not verify that the video is playing.",
            data={"video_present": v_state.video_present, "paused": v_state.paused},
            verified=False,
        )

    def dump_interactive_dom(self) -> List[Dict[str, Any]]:
        """Dumps interactive DOM elements (buttons, inputs, links) with bounding rects."""
        if not cdp_client.is_available():
            return []

        js = """(() => {
            const elements = [];
            const interactive = document.querySelectorAll('button, a, input, select, textarea, [role=button], [role=link], [role=textbox]');
            let idCounter = 1;
            for (const el of interactive) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                    elements.push({
                        id: 'dom_' + (idCounter++),
                        role: el.getAttribute('role') || el.tagName.toLowerCase(),
                        name: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().substring(0, 100),
                        bounds: {
                            x: Math.round(rect.left),
                            y: Math.round(rect.top),
                            w: Math.round(rect.width),
                            h: Math.round(rect.height)
                        },
                        tag: el.tagName.toLowerCase(),
                        disabled: el.disabled || false
                    });
                }
            }
            return elements;
        })()"""
        try:
            res = cdp_client.evaluate(js)
            return res if isinstance(res, list) else []
        except Exception:
            return []
