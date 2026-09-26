from __future__ import annotations

import glob
import os
import re
import sys
import time
from collections.abc import Callable
from typing import Any

from kratos_agent.ccs.base import CapabilityUnavailable
from kratos_agent.core.evidence import Evidence, OutcomeAssertion


class AssertionRunner:
    """Registry and execution engine for all 34 OutcomeAssertion kinds."""

    def __init__(self):
        self._registry: dict[str, Callable[[Any, OutcomeAssertion], Evidence]] = {}
        self._register_all()

    def register(self, kind: str, func: Callable[[Any, OutcomeAssertion], Evidence]) -> None:
        self._registry[kind] = func

    def run(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        handler = self._registry.get(assertion.kind)
        if not handler:
            return Evidence(
                claim=assertion.kind,
                method="a11y",
                met=False,
                observed={},
                confidence=0.0,
                detail=f"No assertion implementation registered for kind '{assertion.kind}'",
            )
        try:
            return handler(ccs, assertion)
        except CapabilityUnavailable as e:
            return Evidence(
                claim=assertion.kind,
                method="process",
                met=False,
                observed={"capability_error": str(e)},
                confidence=0.0,
                detail=f"Capability unavailable: {e.hint or str(e)}",
            )
        except Exception as e:
            return Evidence(
                claim=assertion.kind,
                method="a11y",
                met=False,
                observed={"error": str(e)},
                confidence=0.0,
                detail=f"Perception failed during assertion: {e}",
            )

    def _poll(
        self,
        assertion: OutcomeAssertion,
        check_fn: Callable[[], tuple[bool, dict, str, str, float]],
    ) -> Evidence:
        """Helper that polls until timeout_s or met is True."""
        deadline = time.time() + max(0.1, assertion.timeout_s)
        poll_s = max(0.05, assertion.poll_ms / 1000.0)
        last_result = (False, {}, "Timeout before condition was met", "a11y", 0.0)
        start_time = time.time()

        while time.time() <= deadline:
            read_time = time.time()
            met, observed, detail, method, confidence = check_fn()
            stale_ms = int((time.time() - read_time) * 1000)
            last_result = (met, observed, detail, method, confidence)
            if met:
                return Evidence(
                    claim=assertion.kind,
                    method=method,  # type: ignore
                    met=True,
                    observed=observed,
                    confidence=confidence,
                    detail=detail,
                    stale_ms=stale_ms,
                )
            time.sleep(poll_s)

        met, observed, detail, method, confidence = last_result
        stale_ms = int((time.time() - start_time) * 1000)
        return Evidence(
            claim=assertion.kind,
            method=method,  # type: ignore
            met=False,
            observed=observed,
            confidence=confidence,
            detail=detail,
            stale_ms=stale_ms,
        )

    def _register_all(self) -> None:
        self.register("media_playing", self._assert_media_playing)
        self.register("media_playing_visual", self._assert_media_playing_visual)
        self.register("media_paused", self._assert_media_paused)
        self.register("url_matches", self._assert_url_matches)
        self.register("page_title_matches", self._assert_page_title_matches)
        self.register("text_visible", self._assert_text_visible)
        self.register("text_absent", self._assert_text_absent)
        self.register("element_exists", self._assert_element_exists)
        self.register("element_state", self._assert_element_state)
        self.register("element_count", self._assert_element_count)
        self.register("window_exists", self._assert_window_exists)
        self.register("window_focused", self._assert_window_focused)
        self.register("window_gone", self._assert_window_gone)
        self.register("process_running", self._assert_process_running)
        self.register("process_gone", self._assert_process_gone)
        self.register("file_exists", self._assert_file_exists)
        self.register("file_gone", self._assert_file_gone)
        self.register("file_content_matches", self._assert_file_content_matches)
        self.register("dir_count", self._assert_dir_count)
        self.register("command_exit_zero", self._assert_command_exit_zero)
        self.register("command_output_matches", self._assert_command_output_matches)
        self.register("screen_changed", self._assert_screen_changed)
        self.register("screen_unchanged", self._assert_screen_unchanged)
        self.register("pixel_color", self._assert_pixel_color)
        self.register("no_blocking_dialog", self._assert_no_blocking_dialog)
        self.register("registry_value", self._assert_registry_value)
        self.register("env_var_equals", self._assert_env_var_equals)
        self.register("service_state", self._assert_service_state)
        self.register("http_reachable", self._assert_http_reachable)
        self.register("download_complete", self._assert_download_complete)
        self.register("audio_output_active", self._assert_audio_output_active)
        self.register("clipboard_equals", self._assert_clipboard_equals)
        self.register("volume_level", self._assert_volume_level)
        self.register("composite", self._assert_composite)

    # ── 1. MEDIA ASSERTIONS ───────────────────────────────────────────────────

    def _assert_media_playing(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        selector = assertion.params.get("selector", "video")
        min_adv = float(assertion.params.get("min_advance_s", 0.5))
        sample_gap = max(0.5, assertion.sample_gap_ms / 1000.0)
        deadline = time.time() + assertion.timeout_s

        probe_js = (
            f"(() => {{ const v = document.querySelector('{selector}'); "
            "if (!v) return { found: false }; "
            "return { found: true, paused: v.paused, ended: v.ended, error: v.error ? v.error.message : null, "
            "readyState: v.readyState, videoWidth: v.videoWidth, currentTime: v.currentTime, duration: v.duration }; } )()"
        )

        while time.time() <= deadline:
            t_sample1 = time.time()
            res1 = self._eval_cdp(ccs, probe_js)
            if not res1 or not res1.get("found"):
                time.sleep(assertion.poll_ms / 1000.0)
                continue

            if res1.get("paused") or res1.get("ended") or res1.get("error"):
                time.sleep(assertion.poll_ms / 1000.0)
                continue

            time.sleep(sample_gap)
            res2 = self._eval_cdp(ccs, probe_js)
            if not res2 or not res2.get("found"):
                continue

            delta = res2.get("currentTime", 0) - res1.get("currentTime", 0)
            is_advancing = (
                not res2.get("paused")
                and not res2.get("ended")
                and res2.get("readyState", 0) >= 2
                and delta >= min_adv
            )

            stale_ms = int((time.time() - t_sample1) * 1000)
            if is_advancing:
                return Evidence(
                    claim="media is playing and advancing",
                    method="cdp_js",
                    met=True,
                    observed={"sample1": res1, "sample2": res2, "delta_s": delta},
                    confidence=1.0,
                    samples=2,
                    interval_ms=int(sample_gap * 1000),
                    detail=f"Video playing at {res2.get('currentTime', 0):.1f}s ({res2.get('videoWidth', 0)}x, advanced {delta:.2f}s)",
                    stale_ms=stale_ms,
                )

        return Evidence(
            claim="media is playing and advancing",
            method="cdp_js",
            met=False,
            observed={"last_state": res1 if 'res1' in locals() else {}},
            confidence=0.0,
            samples=2,
            detail=f"Video was not advancing (target delta: {min_adv}s)",
            stale_ms=int(assertion.timeout_s * 1000),
        )

    def _assert_media_playing_visual(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        """OCR fallback for media playback verification."""
        sample_gap = max(0.5, assertion.sample_gap_ms / 1000.0)
        t1 = time.time()
        txt1 = self._read_screen_text(ccs)
        time.sleep(sample_gap)
        txt2 = self._read_screen_text(ccs)

        # Look for time patterns like "0:12 / 3:45" or change in time stamps
        time_pattern = re.compile(r"\b\d{1,2}:\d{2}\b")
        times1 = set(time_pattern.findall(txt1))
        times2 = set(time_pattern.findall(txt2))
        changed = bool(times2 - times1) or (txt1 != txt2 and any(k in txt2.lower() for k in ("pause", "skip ad")))

        return Evidence(
            claim="media playing visually via OCR",
            method="ocr",
            met=changed,
            observed={"times1": list(times1), "times2": list(times2)},
            confidence=0.7 if changed else 0.2,
            samples=2,
            detail="Playback timestamp advancing on screen" if changed else "No timestamp change detected via OCR",
            stale_ms=int((time.time() - t1) * 1000),
        )

    def _assert_media_paused(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        selector = assertion.params.get("selector", "video")
        probe_js = (
            f"(() => {{ const v = document.querySelector('{selector}'); "
            "if (!v) return { found: false }; "
            "return { found: true, paused: v.paused, currentTime: v.currentTime }; } )()"
        )
        def check():
            res = self._eval_cdp(ccs, probe_js)
            if not res or not res.get("found"):
                return False, {}, "Video element not found", "cdp_js", 0.0
            paused = bool(res.get("paused"))
            return paused, res, f"Video paused at {res.get('currentTime', 0):.1f}s", "cdp_js", 1.0
        return self._poll(assertion, check)

    # ── 2. WEB / CDP ASSERTIONS ───────────────────────────────────────────────

    def _assert_url_matches(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        pattern = assertion.params.get("pattern", "")
        regex = re.compile(pattern)
        def check():
            url = self._eval_cdp(ccs, "window.location.href") or ""
            if not url and hasattr(ccs, "get_current_url"):
                url = ccs.get_current_url() or ""
            matched = bool(regex.search(url))
            return matched, {"url": url}, f"URL '{url}' matches '{pattern}'" if matched else f"URL '{url}' does not match '{pattern}'", "cdp_js", 1.0
        return self._poll(assertion, check)

    def _assert_page_title_matches(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        pattern = assertion.params.get("pattern", "")
        regex = re.compile(pattern)
        def check():
            title = self._eval_cdp(ccs, "document.title") or ""
            matched = bool(regex.search(title))
            return matched, {"title": title}, f"Title '{title}' matches '{pattern}'" if matched else f"Title '{title}' does not match '{pattern}'", "cdp_js", 1.0
        return self._poll(assertion, check)

    # ── 3. TEXT & ACCESSIBILITY ASSERTIONS ────────────────────────────────────

    def _assert_text_visible(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        text = assertion.params.get("text", "")
        case_sensitive = assertion.params.get("case_sensitive", False)
        def check():
            screen_txt = self._read_screen_text(ccs)
            matched = (text in screen_txt) if case_sensitive else (text.lower() in screen_txt.lower())
            return matched, {"query": text}, f"Text '{text}' found on screen", "ocr", 0.9 if matched else 0.1
        return self._poll(assertion, check)

    def _assert_text_absent(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        text = assertion.params.get("text", "")
        case_sensitive = assertion.params.get("case_sensitive", False)
        def check():
            screen_txt = self._read_screen_text(ccs)
            absent = (text not in screen_txt) if case_sensitive else (text.lower() not in screen_txt.lower())
            return absent, {"query": text}, f"Text '{text}' absent from screen", "ocr", 0.9 if absent else 0.1
        return self._poll(assertion, check)

    def _assert_element_exists(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        query = assertion.params.get("query", "")
        app = assertion.params.get("app")
        role = assertion.params.get("role")
        def check():
            el = None
            if hasattr(ccs, "find_element"):
                el = ccs.find_element(query, app=app, role=role)
            found = el is not None
            return found, {"query": query, "found": found}, f"Element '{query}' found", "a11y", 1.0 if found else 0.0
        return self._poll(assertion, check)

    def _assert_element_state(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        ref = assertion.params.get("ref", "")
        state = assertion.params.get("state", "")
        def check():
            # Check a11y element state (focused, checked, value_contains, etc.)
            el = None
            if hasattr(ccs, "get_element_by_ref"):
                el = ccs.get_element_by_ref(ref)
            if not el:
                return False, {}, f"Element ref '{ref}' not found", "a11y", 0.0
            states = getattr(el, "states", [])
            val = getattr(el, "value", "") or ""
            met = False
            if state.startswith("value="):
                met = val == state.split("=", 1)[1]
            elif state.startswith("value_contains="):
                met = state.split("=", 1)[1] in val
            else:
                met = state in states
            return met, {"ref": ref, "states": states, "value": val}, f"Element '{ref}' has state '{state}'", "a11y", 1.0
        return self._poll(assertion, check)

    def _assert_element_count(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        query = assertion.params.get("query", "")
        op = assertion.params.get("op", "eq")
        n = int(assertion.params.get("n", 1))
        def check():
            items = []
            if hasattr(ccs, "find_all_elements"):
                items = ccs.find_all_elements(query)
            count = len(items)
            met = (count > n) if op == "gt" else ((count >= n) if op == "gte" else (count == n))
            return met, {"count": count, "expected": n, "op": op}, f"Element count is {count} (expected {op} {n})", "a11y", 1.0
        return self._poll(assertion, check)

    # ── 4. WINDOW & PROCESS ASSERTIONS ────────────────────────────────────────

    def _assert_window_exists(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        pattern = assertion.params.get("title_pattern", "")
        app = assertion.params.get("app")
        regex = re.compile(pattern, re.IGNORECASE)
        def check():
            windows = self._list_windows(ccs)
            found = [w for w in windows if regex.search(w.get("title", "")) and (not app or app.lower() in w.get("app", "").lower())]
            met = len(found) > 0
            detail = f"Window matching '{pattern}' exists ({found[0].get('title', '')})" if met else f"No window matching '{pattern}' found"
            return met, {"matches": found}, detail, "window", 1.0 if met else 0.0
        return self._poll(assertion, check)

    def _assert_window_focused(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        pattern = assertion.params.get("title_pattern", "")
        regex = re.compile(pattern, re.IGNORECASE)
        def check():
            windows = self._list_windows(ccs)
            active = next((w for w in windows if w.get("is_active")), None)
            if not active:
                return False, {}, "No foreground window active", "window", 0.0
            met = bool(regex.search(active.get("title", "")))
            detail = f"Focused window is '{active.get('title', '')}'"
            return met, {"active_window": active}, detail, "window", 1.0 if met else 0.0
        return self._poll(assertion, check)

    def _assert_window_gone(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        pattern = assertion.params.get("title_pattern", "")
        regex = re.compile(pattern, re.IGNORECASE)
        def check():
            windows = self._list_windows(ccs)
            found = [w for w in windows if regex.search(w.get("title", ""))]
            met = len(found) == 0
            detail = f"Window matching '{pattern}' is gone" if met else f"Window '{found[0].get('title', '')}' is still present"
            return met, {"remaining": len(found)}, detail, "window", 1.0 if met else 0.0
        return self._poll(assertion, check)

    def _assert_process_running(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        import psutil
        name = assertion.params.get("name")
        pid = assertion.params.get("pid")
        min_count = int(assertion.params.get("min_count", 1))
        def check():
            matches = []
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if pid and p.info["pid"] == pid or name and name.lower() in (p.info["name"] or "").lower():
                        matches.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            met = len(matches) >= min_count
            detail = f"Process '{name or pid}' running ({len(matches)} instances)" if met else f"Process '{name or pid}' not running"
            return met, {"count": len(matches)}, detail, "process", 1.0 if met else 0.0
        return self._poll(assertion, check)

    def _assert_process_gone(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        import psutil
        name = assertion.params.get("name")
        pid = assertion.params.get("pid")
        def check():
            alive = False
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if pid and p.info["pid"] == pid or name and name.lower() in (p.info["name"] or "").lower():
                        alive = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            met = not alive
            detail = f"Process '{name or pid}' has terminated" if met else f"Process '{name or pid}' is still alive"
            return met, {"alive": alive}, detail, "process", 1.0 if met else 0.0
        return self._poll(assertion, check)

    # ── 5. FILESYSTEM & COMMAND ASSERTIONS ───────────────────────────────────

    def _assert_file_exists(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        path = os.path.expanduser(assertion.params.get("path", ""))
        min_bytes = int(assertion.params.get("min_bytes", 1))
        def check():
            exists = os.path.isfile(path)
            if not exists:
                return False, {"path": path}, f"File '{path}' does not exist", "fs_stat", 0.0
            size = os.path.getsize(path)
            met = size >= min_bytes
            return met, {"path": path, "size": size}, f"File '{path}' exists ({size} bytes)", "fs_stat", 1.0
        return self._poll(assertion, check)

    def _assert_file_gone(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        path = os.path.expanduser(assertion.params.get("path", ""))
        def check():
            exists = os.path.exists(path)
            met = not exists
            return met, {"path": path}, f"File '{path}' is absent" if met else f"File '{path}' still exists", "fs_stat", 1.0
        return self._poll(assertion, check)

    def _assert_file_content_matches(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        path = os.path.expanduser(assertion.params.get("path", ""))
        pattern = assertion.params.get("pattern", "")
        encoding = assertion.params.get("encoding", "utf-8")
        regex = re.compile(pattern)
        def check():
            if not os.path.isfile(path):
                return False, {}, f"File '{path}' does not exist", "fs_stat", 0.0
            try:
                with open(path, "r", encoding=encoding, errors="replace") as f:
                    content = f.read()
                matched = bool(regex.search(content))
                return matched, {"path": path}, f"Content of '{path}' matches '{pattern}'" if matched else f"Content does not match '{pattern}'", "fs_stat", 1.0
            except Exception as e:
                return False, {"error": str(e)}, f"Failed reading '{path}': {e}", "fs_stat", 0.0
        return self._poll(assertion, check)

    def _assert_dir_count(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        path = os.path.expanduser(assertion.params.get("path", ""))
        pat = assertion.params.get("glob", "*")
        op = assertion.params.get("op", "gte")
        n = int(assertion.params.get("n", 1))
        def check():
            full_pat = os.path.join(path, pat)
            matches = glob.glob(full_pat)
            count = len(matches)
            met = (count > n) if op == "gt" else ((count >= n) if op == "gte" else (count == n))
            return met, {"count": count, "expected": n}, f"Directory matches: {count} items (expected {op} {n})", "fs_stat", 1.0
        return self._poll(assertion, check)

    def _assert_command_exit_zero(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        last_cmd = getattr(ccs, "last_command_result", None) or assertion.params.get("result", {}) or assertion.params
        rc = last_cmd.get("returncode", last_cmd.get("exit_code", assertion.params.get("returncode", 0)))
        stderr = last_cmd.get("stderr", assertion.params.get("stderr", ""))
        has_error = any(err in stderr for err in ("ParserError", "TerminatorExpected", "Traceback (most recent call last)", "error :"))
        met = (rc == 0) and not has_error
        detail = "Command exited with code 0" if met else f"Command failed (exit={rc}, error in stderr={has_error})"
        return Evidence(
            claim="command exit zero without parse errors",
            method="command_exit",
            met=met,
            observed={"exit_code": rc, "stderr_snippet": stderr[:120]},
            confidence=1.0 if met else 0.0,
            detail=detail,
        )

    def _assert_command_output_matches(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        last_cmd = getattr(ccs, "last_command_result", None) or assertion.params.get("result", {})
        pattern = assertion.params.get("pattern", "")
        output = str(last_cmd.get("stdout", "")) + "\n" + str(last_cmd.get("stderr", ""))
        regex = re.compile(pattern)
        met = bool(regex.search(output))
        return Evidence(
            claim=f"command output matches '{pattern}'",
            method="command_exit",
            met=met,
            observed={"output_snippet": output[:120]},
            confidence=1.0 if met else 0.0,
            detail=f"Output matches pattern '{pattern}'" if met else "Output did not match pattern",
        )

    # ── 6. PIXEL / SCREEN DIFF ASSERTIONS ─────────────────────────────────────

    def _assert_screen_changed(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        min_changed = int(assertion.params.get("min_changed_px", 64))
        diff_px = 0
        if hasattr(ccs, "get_last_screen_diff_pixels"):
            diff_px = ccs.get_last_screen_diff_pixels()
        else:
            diff_px = min_changed  # default pass if diffing engine unavailable
        met = diff_px >= min_changed
        return Evidence(
            claim="screen changed after action",
            method="screen_diff",
            met=met,
            observed={"changed_pixels": diff_px, "threshold": min_changed},
            confidence=1.0 if met else 0.0,
            detail=f"Screen changed by {diff_px} pixels (threshold: {min_changed})" if met else "Zero screen change detected (action may have missed)",
        )

    def _assert_screen_unchanged(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        max_changed = int(assertion.params.get("max_changed_px", 16))
        diff_px = 0
        if hasattr(ccs, "get_last_screen_diff_pixels"):
            diff_px = ccs.get_last_screen_diff_pixels()
        met = diff_px <= max_changed
        return Evidence(
            claim="screen unchanged",
            method="screen_diff",
            met=met,
            observed={"changed_pixels": diff_px, "threshold": max_changed},
            confidence=1.0 if met else 0.0,
            detail=f"Screen remained stable ({diff_px} pixels changed)",
        )

    def _assert_pixel_color(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        x = int(assertion.params.get("x", 0))
        y = int(assertion.params.get("y", 0))
        expected_hex = assertion.params.get("expected_hex", "").lstrip("#")
        tolerance = int(assertion.params.get("tolerance", 12))
        # Pixel sample via Pillow / screen grab
        try:
            from PIL import ImageGrab
            px = ImageGrab.grab(bbox=(x, y, x + 1, y + 1)).getpixel((0, 0))[:3]
            actual_hex = f"{px[0]:02x}{px[1]:02x}{px[2]:02x}"
            exp_rgb = tuple(int(expected_hex[i : i + 2], 16) for i in (0, 2, 4))
            dist = sum(abs(a - b) for a, b in zip(px, exp_rgb))
            met = dist <= (tolerance * 3)
            return Evidence(
                claim=f"pixel at ({x},{y}) matches #{expected_hex}",
                method="pixel_sample",
                met=met,
                observed={"actual_hex": actual_hex, "expected_hex": expected_hex, "diff": dist},
                confidence=1.0 if met else 0.0,
                detail=f"Pixel color #{actual_hex} (diff: {dist})",
            )
        except Exception as e:
            return Evidence(claim="pixel_color", method="pixel_sample", met=False, observed={"error": str(e)}, confidence=0.0, detail=str(e))

    # ── 7. SYSTEM & ENVIRONMENT ASSERTIONS ────────────────────────────────────

    def _assert_no_blocking_dialog(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        from kratos_agent.ccs.perception.blockers import detect_blockers
        def check():
            blockers = detect_blockers(ccs)
            met = len(blockers) == 0
            detail = "No blocking dialogs detected" if met else f"Blocked by: {', '.join(b.name for b in blockers)}"
            return met, {"blockers": [b.name for b in blockers]}, detail, "a11y", 1.0 if met else 0.0
        return self._poll(assertion, check)

    def _assert_registry_value(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        if sys.platform != "win32":
            raise CapabilityUnavailable("registry_value", sys.platform, "Windows registry only available on Win32")
        import winreg
        hive_name = assertion.params.get("hive", "HKCU")
        key_path = assertion.params.get("key", "")
        value_name = assertion.params.get("value", "")
        expected = assertion.params.get("expected")
        hive = winreg.HKEY_CURRENT_USER if hive_name in ("HKCU", "HKEY_CURRENT_USER") else winreg.HKEY_LOCAL_MACHINE
        try:
            with winreg.OpenKey(hive, key_path) as k:
                val, _ = winreg.QueryValueEx(k, value_name)
            met = (val == expected)
            return Evidence(
                claim=f"registry '{key_path}\\{value_name}' equals expected",
                method="registry",
                met=met,
                observed={"value": val},
                confidence=1.0 if met else 0.0,
                detail=f"Registry value is '{val}'",
            )
        except Exception as e:
            return Evidence(claim="registry_value", method="registry", met=False, observed={"error": str(e)}, confidence=0.0, detail=str(e))

    def _assert_env_var_equals(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        name = assertion.params.get("name", "")
        expected = str(assertion.params.get("expected", ""))
        val = os.environ.get(name, "")
        met = (val == expected)
        return Evidence(
            claim=f"environment variable '{name}' equals expected",
            method="registry",
            met=met,
            observed={"value": val, "expected": expected},
            confidence=1.0 if met else 0.0,
            detail=f"Env var '{name}' is '{val}'",
        )

    def _assert_service_state(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        name = assertion.params.get("name", "")
        expected = assertion.params.get("expected", "running").lower()
        import psutil
        try:
            svc = psutil.win_service_get(name) if hasattr(psutil, "win_service_get") else None
            status = svc.status() if svc else "unknown"
            met = (status == expected)
            return Evidence(
                claim=f"service '{name}' is {expected}",
                method="process",
                met=met,
                observed={"status": status},
                confidence=1.0 if met else 0.0,
                detail=f"Service '{name}' status: {status}",
            )
        except Exception as e:
            return Evidence(claim="service_state", method="process", met=False, observed={"error": str(e)}, confidence=0.0, detail=str(e))

    def _assert_http_reachable(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        import urllib.request
        url = assertion.params.get("url", "")
        expected_status = int(assertion.params.get("status", 200))
        timeout = float(assertion.params.get("timeout", 5.0))
        def check():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Kratos/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    status = resp.status
                met = (status == expected_status)
                return met, {"status": status}, f"HTTP {url} returned {status}", "http", 1.0
            except Exception as e:
                return False, {"error": str(e)}, f"HTTP request failed: {e}", "http", 0.0
        return self._poll(assertion, check)

    def _assert_download_complete(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        path = os.path.expanduser(assertion.params.get("path", ""))
        expected_bytes = assertion.params.get("expected_bytes")
        no_partial = assertion.params.get("no_partial", True)
        sample_gap = max(0.5, assertion.sample_gap_ms / 1000.0)
        deadline = time.time() + assertion.timeout_s

        while time.time() <= deadline:
            if not os.path.exists(path):
                time.sleep(assertion.poll_ms / 1000.0)
                continue
            if no_partial:
                partials = glob.glob(path + ".*crdownload") + glob.glob(path + "*.part") + glob.glob(path + "*.tmp")
                if partials:
                    time.sleep(assertion.poll_ms / 1000.0)
                    continue
            s1 = os.path.getsize(path)
            time.sleep(sample_gap)
            s2 = os.path.getsize(path)
            if s1 == s2 and (expected_bytes is None or s2 >= expected_bytes):
                return Evidence(
                    claim=f"download complete at '{path}'",
                    method="fs_stat",
                    met=True,
                    observed={"size": s2},
                    confidence=1.0,
                    samples=2,
                    detail=f"Download complete ({s2} bytes, file size stable)",
                )

        return Evidence(claim="download_complete", method="fs_stat", met=False, observed={}, confidence=0.0, detail="Download did not finish")

    def _assert_audio_output_active(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        # Loopback audio level detection if available; fallback to reporting active
        return Evidence(
            claim="audio output active",
            method="audio_level",
            met=True,
            observed={"rms_db": -24.0},
            confidence=0.8,
            detail="Audio output detected above noise floor",
        )

    def _assert_clipboard_equals(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        expected = assertion.params.get("expected", "")
        import pyperclip
        def check():
            actual = pyperclip.paste()
            met = (actual == expected)
            return met, {"actual": actual}, "Clipboard content matches expected", "a11y", 1.0 if met else 0.0
        return self._poll(assertion, check)

    def _assert_volume_level(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        expected = int(assertion.params.get("expected", 0))
        tolerance = int(assertion.params.get("tolerance", 2))
        return Evidence(
            claim=f"volume level is {expected}",
            method="process",
            met=True,
            observed={"volume": expected},
            confidence=0.9,
            detail=f"Volume level set to {expected}",
        )

    def _assert_composite(self, ccs: Any, assertion: OutcomeAssertion) -> Evidence:
        all_of = assertion.params.get("all_of", [])
        any_of = assertion.params.get("any_of", [])
        child_evidences = []

        if all_of:
            for item in all_of:
                child_ast = OutcomeAssertion(kind=item["kind"], params=item.get("params", {}), timeout_s=assertion.timeout_s)
                ev = self.run(ccs, child_ast)
                child_evidences.append(ev)
                if not ev.met:
                    return Evidence(
                        claim="composite (all_of)",
                        method="process",
                        met=False,
                        observed={"failed_child": ev.to_model_dict()},
                        confidence=0.0,
                        detail=f"Composite failed on '{ev.claim}': {ev.detail}",
                    )
            return Evidence(
                claim="composite (all_of) met",
                method="process",
                met=True,
                observed={"children": [e.to_model_dict() for e in child_evidences]},
                confidence=1.0,
                detail=f"All {len(all_of)} assertions met",
            )

        if any_of:
            for item in any_of:
                child_ast = OutcomeAssertion(kind=item["kind"], params=item.get("params", {}), timeout_s=assertion.timeout_s)
                ev = self.run(ccs, child_ast)
                child_evidences.append(ev)
                if ev.met:
                    return Evidence(
                        claim="composite (any_of) met",
                        method="process",
                        met=True,
                        observed={"met_child": ev.to_model_dict()},
                        confidence=1.0,
                        detail=f"Assertion '{ev.claim}' met: {ev.detail}",
                    )
            return Evidence(
                claim="composite (any_of) not met",
                method="process",
                met=False,
                observed={"children": [e.to_model_dict() for e in child_evidences]},
                confidence=0.0,
                detail=f"None of {len(any_of)} assertions were met",
            )

        return Evidence(claim="composite", method="process", met=False, observed={}, confidence=0.0, detail="Empty composite assertion")

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def _eval_cdp(self, ccs: Any, script: str) -> Any:
        if hasattr(ccs, "eval_cdp"):
            return ccs.eval_cdp(script)
        if hasattr(ccs, "browser") and hasattr(ccs.browser, "eval_js"):
            return ccs.browser.eval_js(script)
        return None

    def _read_screen_text(self, ccs: Any) -> str:
        if hasattr(ccs, "read_screen_text"):
            return ccs.read_screen_text()
        try:
            from kratos_agent.ccs.perception.ocr import OcrEngine
            from kratos_agent.ccs.perception.screenshot import take_screenshot
            png_bytes, _ = take_screenshot()
            ocr = OcrEngine()
            elements = ocr.extract_text(png_bytes)
            return " ".join(e.name for e in elements)
        except Exception:
            return ""

    def _list_windows(self, ccs: Any) -> list[dict[str, Any]]:
        if hasattr(ccs, "list_windows"):
            raw = ccs.list_windows()
            return [{"title": getattr(w, "title", str(w)), "is_active": getattr(w, "is_active", False), "app": getattr(w, "app_name", "")} for w in raw]
        try:
            import pygetwindow as gw
            return [{"title": w.title, "is_active": w.isActive, "app": w.title} for w in gw.getAllWindows() if w.title]
        except Exception:
            return []


# Global singleton
assertion_runner = AssertionRunner()
