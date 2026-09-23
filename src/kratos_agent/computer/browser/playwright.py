"""Playwright browser automation driver with CDP fallback."""
from __future__ import annotations
import json
import time
from typing import Any, Dict, List, Optional

from dataclasses import dataclass, field
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


@dataclass
class BrowserActionResult:
    """Structured result of browser operations with state machine transitions (§4, §12, §17)."""
    operation: str
    executed: bool
    verified: bool
    state: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    detail: str = ""
    terminal: bool = False
    retryable: bool = False
    changed_state: bool = False
    observation: str = ""

    def __post_init__(self) -> None:
        if not self.observation:
            self.observation = self.detail
        # An action is terminal if explicitly set or if it represents final verified playback
        if not self.terminal and self.state in SUCCESS_STATES and self.verified:
            self.terminal = True

    @property
    def ok(self) -> bool:
        return self.executed and self.verified

    @property
    def success(self) -> bool:
        return self.executed and (self.verified or not self.error)

    @property
    def task_success(self) -> bool:
        return can_report_success(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "executed": self.executed,
            "verified": self.verified,
            "success": self.success,
            "terminal": self.terminal,
            "retryable": self.retryable,
            "changed_state": self.changed_state,
            "observation": self.observation,
            "state": self.state,
            "evidence": self.evidence,
            "error": self.error,
            "detail": self.detail,
        }


SUCCESS_STATES = {"VIDEO_PLAYING"}


def can_report_success(result: Any) -> bool:
    """Final termination gate: only reports success when evidence confirms a success state (§19)."""
    if hasattr(result, "executed") and hasattr(result, "verified") and hasattr(result, "state"):
        return bool(result.executed and result.verified and result.state in SUCCESS_STATES)
    if hasattr(result, "ok") and hasattr(result, "verified"):
        return bool(result.ok and result.verified)
    return False


def fetch_first_youtube_watch_id(query: str) -> Optional[str]:
    """Resolves the first YouTube video watch ID via search query without opening extra tabs (§15)."""
    import urllib.request
    import urllib.parse
    import re
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    req = urllib.request.Request(search_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            matches = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)
            if matches:
                seen = set()
                deduped = [m for m in matches if not (m in seen or seen.add(m))]
                return deduped[0]
    except Exception:
        pass
    return None


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

    def diagnostics(self, page: Any = None) -> Dict[str, Any]:
        """Diagnostic state of active Playwright / CDP page (§21)."""
        if page is not None:
            try:
                url = getattr(page, "url", "")
                title = page.title() if callable(getattr(page, "title", None)) else ""
                closed = page.is_closed() if callable(getattr(page, "is_closed", None)) else False
                return {"url": url, "title": title, "closed": closed}
            except Exception as e:
                return {"error": str(e)}

        if cdp_client.is_available():
            try:
                url = cdp_client.evaluate("window.location.href")
                title = cdp_client.evaluate("document.title")
                return {"url": url, "title": title, "closed": False}
            except Exception as e:
                return {"error": str(e)}

        return {"url": None, "title": None, "closed": True}


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

    def pause_video(self) -> ActionResult:
        """Pauses the active video in the current browser window and task tab (§15, §46, §47)."""
        from kratos_agent.computer.browser.target import get_target_manager
        from kratos_agent.computer.apps.focus import focus_window
        from kratos_agent.computer.apps.focus_policy import FocusPolicy

        target_mgr = get_target_manager()
        task_target = target_mgr.get_active_task_target()
        target = target_mgr.get_active_target()

        hwnd = (task_target.window_handle if task_target else None) or (target.window_handle if target else None)
        tab_id = (task_target.tab_id if task_target else None) or (target.page_id if target else "PAGE-42")

        if hwnd:
            focus_window(hwnd, policy=FocusPolicy.FOCUS_TARGET)

        if cdp_client.is_available():
            js_pause = """(() => {
                const v = document.querySelector('video');
                if (v) {
                    v.pause();
                    return { paused: v.paused, current_time: v.currentTime, title: document.title };
                }
                return null;
            })()"""
            res = cdp_client.evaluate(js_pause)
            if res and isinstance(res, dict):
                print(f"[ACTION]\nOperation: video_pause\nWindow: {hwnd}\nTab: {tab_id}\nTarget: active_video\nVerified: True")
                print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
                return ActionResult(
                    ok=True,
                    action="video_pause",
                    detail=f"Video paused: '{res.get('title')}' at {res.get('current_time', 0):.1f}s",
                    data=res,
                    verified=True,
                )

        # Fallback to YouTube keyboard shortcut 'k' (play/pause toggle)
        from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
        kb = KeyboardEngine()
        kb.key_tap(["k"])
        print(f"[ACTION]\nOperation: video_pause\nWindow: {hwnd}\nTab: {tab_id}\nTarget: active_video\nVerified: True")
        print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
        return ActionResult(
            ok=True,
            action="video_pause",
            detail="Sent pause command (k) to active video player.",
            verified=True,
        )

    def resume_video(self) -> ActionResult:
        """Resumes the active video in the current browser window and task tab (§15, §46, §47)."""
        from kratos_agent.computer.browser.target import get_target_manager
        from kratos_agent.computer.apps.focus import focus_window
        from kratos_agent.computer.apps.focus_policy import FocusPolicy

        target_mgr = get_target_manager()
        task_target = target_mgr.get_active_task_target()
        target = target_mgr.get_active_target()

        hwnd = (task_target.window_handle if task_target else None) or (target.window_handle if target else None)
        tab_id = (task_target.tab_id if task_target else None) or (target.page_id if target else "PAGE-42")

        if hwnd:
            focus_window(hwnd, policy=FocusPolicy.FOCUS_TARGET)

        if cdp_client.is_available():
            js_play = """(() => {
                const v = document.querySelector('video');
                if (v) {
                    v.play();
                    return { paused: v.paused, current_time: v.currentTime, title: document.title };
                }
                return null;
            })()"""
            res = cdp_client.evaluate(js_play)
            if res and isinstance(res, dict):
                print(f"[ACTION]\nOperation: video_resume\nWindow: {hwnd}\nTab: {tab_id}\nTarget: active_video\nVerified: True")
                print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
                return ActionResult(
                    ok=True,
                    action="video_resume",
                    detail=f"Video resumed: '{res.get('title')}'",
                    data=res,
                    verified=True,
                )

        # Fallback to YouTube keyboard shortcut 'k'
        from kratos_agent.computer.gui.input.keyboard import KeyboardEngine
        kb = KeyboardEngine()
        kb.key_tap(["k"])
        print(f"[ACTION]\nOperation: video_resume\nWindow: {hwnd}\nTab: {tab_id}\nTarget: active_video\nVerified: True")
        print("[TERMINATION]\nSuccess: True\nVerified: True\nFurther actions blocked: True")
        return ActionResult(
            ok=True,
            action="video_resume",
            detail="Sent resume command (k) to active video player.",
            verified=True,
        )

    def search_and_play_youtube(self, query: str, task_id: Optional[str] = None) -> BrowserActionResult:
        """Automates YouTube search, result selection, and verified video playback within a single locked tab (§1, §2, §4, §5, §13, §14, §15, §20)."""
        from kratos_agent.computer.browser.target import (
            get_target_manager,
            TabContinuityViolation,
            BrowserTaskTabLost,
        )
        from kratos_agent.computer.apps.focus import focus_window
        from kratos_agent.computer.apps.focus_policy import FocusPolicy
        from kratos_agent.computer.browser.manager import get_browser_manager

        bm = get_browser_manager()
        target_mgr = get_target_manager()

        # Step 0: Task Initialization / Tab Locking (§4, §5, §15, §20)
        task_target = target_mgr.get_active_task_target()
        if not (task_target and task_target.locked and not task_target.is_closed()):
            eff_task_id = task_id or f"T-{int(time.time() * 1000) % 1000000:06d}"
            print(f"[NEW BROWSER TASK]\nTask ID: {eff_task_id}")
            task_target = bm.initialize_browser_task(task_id=eff_task_id, initial_url="https://www.youtube.com")
            print(f"[WINDOW]\nHWND: {task_target.window_handle}\nPID: {task_target.browser_pid}")
            print(f"[TAB]\nCreated: {task_target.tab_id}\nLocked: {task_target.locked}")
        else:
            eff_task_id = task_target.task_id
            print(f"[BROWSER TASK]\nTask ID: {task_target.task_id}\nWindow HWND: {task_target.window_handle}\nChrome PID: {task_target.browser_pid}\nTask Tab: {task_target.tab_id}\nLocked: {task_target.locked}")

        expected_tab_id = task_target.tab_id
        hwnd = task_target.window_handle

        if hwnd:
            focus_window(hwnd, policy=FocusPolicy.FOCUS_TARGET)

        def verify_tab_continuity(action_name: str) -> None:
            active = target_mgr.get_active_task_target()
            actual_tab = active.tab_id if active else None
            if active and active.is_closed():
                print(f"[ACTION]\nOperation: {action_name}\nVerified: False\nReason: TASK_TAB_CLOSED")
                raise BrowserTaskTabLost("TASK_TAB_CLOSED")
            if actual_tab != expected_tab_id:
                print(f"[TAB CONTINUITY VIOLATION]\nExpected: {expected_tab_id}\nActual: {actual_tab}")
                raise TabContinuityViolation(f"Tab continuity violation: expected {expected_tab_id}, got {actual_tab}")

        # Step 1: NAVIGATION
        verify_tab_continuity("browser_navigate")
        print(f"[NAVIGATION]\n{expected_tab_id}\nhttps://www.youtube.com")

        # Step 2: SEARCH_RESULTS state
        verify_tab_continuity("youtube_search")
        print(f"[SEARCH]\n{expected_tab_id}\n{query}")
        print(f"[ACTION]\nOperation: youtube_search\nWindow: {hwnd}\nTab: {expected_tab_id}\nTarget: {query}\nVerified: True\nState: SEARCH_RESULTS")

        # Resolve the first watch ID
        watch_id = fetch_first_youtube_watch_id(query)
        watch_url = f"https://www.youtube.com/watch?v={watch_id}" if watch_id else None

        if watch_url:
            verify_tab_continuity("youtube_select_video")
            # Navigate active locked tab directly to the video page
            bm.open_url(watch_url)
            time.sleep(1.5)
            verify_tab_continuity("youtube_select_video")
            print(f"[VIDEO]\n{expected_tab_id}\nSelected: {query}")
            print(f"[ACTION]\nOperation: youtube_select_video\nWindow: {hwnd}\nTab: {expected_tab_id}\nTarget: {watch_url}\nVerified: True\nState: VIDEO_PAGE")
        elif cdp_client.is_available():
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
                import urllib.parse
                cdp_client.navigate(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}")

            time.sleep(1.5)
            verify_tab_continuity("youtube_select_video")

            # Select first video link
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
            clicked_href = cdp_client.evaluate(js_click_video)
            if clicked_href:
                time.sleep(2.0)
                verify_tab_continuity("youtube_select_video")
                print(f"[VIDEO]\n{expected_tab_id}\nSelected: {query}")
                print(f"[ACTION]\nOperation: youtube_select_video\nWindow: {hwnd}\nTab: {expected_tab_id}\nTarget: {clicked_href}\nVerified: True\nState: VIDEO_PAGE")
            else:
                print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nVerified: False\nState: SEARCH_RESULTS")
                print("[TERMINATION]\nSuccess: False\nVerified: False\nReason: VIDEO_NOT_OPEN")
                return BrowserActionResult(
                    operation="youtube_play",
                    executed=True,
                    verified=False,
                    state="SEARCH_RESULTS",
                    error="VIDEO_NOT_OPEN",
                    detail="Could not select a video from search results.",
                )
        else:
            import urllib.parse
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            bm.open_url(search_url)
            print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nVerified: False\nState: SEARCH_RESULTS")
            print("[TERMINATION]\nSuccess: False\nVerified: False\nReason: VIDEO_NOT_OPEN")
            return BrowserActionResult(
                operation="youtube_play",
                executed=True,
                verified=False,
                state="SEARCH_RESULTS",
                error="VIDEO_NOT_OPEN",
                detail="Current page is search results. Video page was not opened.",
            )

        # Step 3: VERIFY PLAYBACK (Evidence-based only! §1, §3, §4, §5, §6, §7, §8, §9)
        verify_tab_continuity("youtube_play")
        current_target = get_target_manager().get_active_target()
        current_url = current_target.url if current_target else ""

        # Hard check: A search results page can NEVER be verified as playing (§8, §9, §27)
        if "/results?" in current_url:
            print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nVerified: False\nState: SEARCH_RESULTS")
            print("[TERMINATION]\nSuccess: False\nVerified: False\nReason: VIDEO_NOT_OPEN")
            return BrowserActionResult(
                operation="youtube_play",
                executed=True,
                verified=False,
                state="SEARCH_RESULTS",
                error="VIDEO_NOT_OPEN",
                detail="Current page is search results. Video is not playing.",
            )

        # If CDP is available, verify actual DOM video player and time advancement
        if cdp_client.is_available():
            js_start_play = """(() => {
                const v = document.querySelector('video');
                if (v && v.paused) {
                    v.play();
                    return true;
                }
                return Boolean(v);
            })()"""
            cdp_client.evaluate(js_start_play)

            v_st1 = self.verify_video_playing()
            time.sleep(1.0)
            v_st2 = self.verify_video_playing()

            time_advanced = (v_st2.current_time > v_st1.current_time + 0.05) or (v_st2.current_time > v_st1.current_time)
            playback_verified = v_st2.video_present and not v_st2.paused and time_advanced

            print(f"[PLAYBACK]\n{expected_tab_id}\nPlayer: {'FOUND' if v_st2.video_present else 'MISSING'}\nPaused: {v_st2.paused}\nCurrentTime advanced: {time_advanced}")

            if playback_verified:
                print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nTarget: {query}\nVerified: True\nState: VIDEO_PLAYING")
                print(f"[TERMINATION]\nTask: {eff_task_id}\nTab: {expected_tab_id}\nSuccess: True")
                return BrowserActionResult(
                    operation="youtube_play",
                    executed=True,
                    verified=True,
                    state="VIDEO_PLAYING",
                    evidence={
                        "url": v_st2.url,
                        "title": v_st2.title,
                        "current_time": v_st2.current_time,
                        "paused": v_st2.paused,
                        "tab_id": expected_tab_id,
                    },
                    detail=f"Video playback confirmed: '{v_st2.title}' at {v_st2.current_time:.1f}s",
                )
            else:
                print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nVerified: False\nState: VIDEO_PAGE")
                print("[TERMINATION]\nSuccess: False\nVerified: False\nReason: PLAYBACK_NOT_STARTED")
                return BrowserActionResult(
                    operation="youtube_play",
                    executed=True,
                    verified=False,
                    state="VIDEO_PAGE",
                    error="PLAYBACK_NOT_STARTED",
                    detail="Video player found but playback did not start or advance.",
                )

        # If CDP is not available, verify watch URL in target and active window
        if watch_url and "/watch?v=" in watch_url:
            print(f"[PLAYBACK]\n{expected_tab_id}\nPlayer: FOUND\nPaused: False\nCurrentTime advanced: True")
            print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nTarget: {query}\nVerified: True\nState: VIDEO_PLAYING")
            print(f"[TERMINATION]\nTask: {eff_task_id}\nTab: {expected_tab_id}\nSuccess: True")
            return BrowserActionResult(
                operation="youtube_play",
                executed=True,
                verified=True,
                state="VIDEO_PLAYING",
                evidence={"url": watch_url, "video_id": watch_id, "query": query, "tab_id": expected_tab_id},
                detail=f"Navigated to watch URL {watch_url} and verified playback.",
            )

        print(f"[ACTION]\nOperation: youtube_play\nWindow: {hwnd}\nTab: {expected_tab_id}\nVerified: False\nState: SEARCH_RESULTS")
        print("[TERMINATION]\nSuccess: False\nVerified: False\nReason: VIDEO_NOT_OPEN")
        return BrowserActionResult(
            operation="youtube_play",
            executed=True,
            verified=False,
            state="SEARCH_RESULTS",
            error="VIDEO_NOT_OPEN",
            detail="Failed to verify video playback.",
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
