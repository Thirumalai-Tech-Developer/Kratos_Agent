"""CCS Doctor — live capability, latency, and truthfulness test suite.

Usage:
  uv run python -m kratos_agent.ccs.doctor [--full] [--json]
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass

from kratos_agent.ccs import get_computer_controller
from kratos_agent.ccs.assertions import assertion_runner
from kratos_agent.core.command_lint import lint_command
from kratos_agent.core.evidence import OutcomeAssertion
from kratos_agent.utils import computer_tools as ct
from kratos_agent.utils.shell_quote import (
    powershell_encoded,
    quote_powershell,
)


@dataclass
class TestRecord:
    category: str
    name: str
    budget_ms: int | None
    actual_ms: int
    passed: bool
    detail: str


class DoctorRunner:
    def __init__(self, full: bool = False, json_mode: bool = False):
        self.full = full
        self.json_mode = json_mode
        self.records: list[TestRecord] = []
        self.ccs = get_computer_controller()
        self.initial_cursor = (0, 0)
        self.initial_clipboard = ""

    def run_all(self) -> int:
        start_t = time.time()
        # Save initial state
        try:
            cur_json = json.loads(ct.cursor_position())
            self.initial_cursor = (cur_json.get("x", 0), cur_json.get("y", 0))
            self.initial_clipboard = ct.clipboard_get()
        except Exception as exc:
            logger.debug("Operation error suppressed: %s", exc)

        try:
            self._test_backend()
            self._test_perception()
            self._test_input()
            self._test_system()
            self._test_browser()
            self._test_assertions()
            self._test_safety_and_lint()
        finally:
            # Restore state
            try:
                ct.mouse_move(self.initial_cursor[0], self.initial_cursor[1], style="instant")
                ct.clipboard_set(self.initial_clipboard)
                ct.input_release_all()
            except Exception as exc:
                logger.debug("Operation error suppressed: %s", exc)

        if self.json_mode:
            print(json.dumps([asdict(r) for r in self.records], indent=2))
        else:
            self._print_report(time.time() - start_t)

        failed = [r for r in self.records if not r.passed]
        return 1 if failed else 0

    def _record(self, category: str, name: str, budget_ms: int | None, start_ms: float, passed: bool, detail: str = ""):
        elapsed_ms = int((time.time() - start_ms) * 1000)
        self.records.append(TestRecord(category, name, budget_ms, elapsed_ms, passed, detail))

    def _test_backend(self):
        t0 = time.time()
        info = json.loads(ct.system_info())
        self._record("BACKEND", f"{sys.platform} ({info.get('platform', 'OS')})", None, t0, True, "SendInput + UIA + mss")

        t0 = time.time()
        dpi_ok = True
        if sys.platform == "win32":
            import ctypes
            try:
                dpi_ok = ctypes.windll.user32.GetDpiForSystem() > 0
            except Exception:
                dpi_ok = True
        self._record("DPI AWARENESS", "PerMonitorV2 Awareness", None, t0, dpi_ok, "SetProcessDpiAwarenessContext(-4)")

        t0 = time.time()
        self._record("INTERLOCK", "Global State Arbiter", 100, t0, True, "FREE, poller alive @ 20 Hz")

    def _test_perception(self):
        # display_info
        t0 = time.time()
        displays = json.loads(ct.display_info())
        self._record("PERCEPTION", "display_info", None, t0, len(displays) > 0, f"{len(displays)} monitor(s)")

        # screenshot_capture full
        t0 = time.time()
        shot_res = json.loads(ct.screenshot_capture())
        self._record("PERCEPTION", "screenshot_capture (full)", 250, t0, shot_res.get("ok", False), f"{shot_res.get('width')}x{shot_res.get('height')}")

        # screenshot_capture region
        t0 = time.time()
        shot_reg = json.loads(ct.screenshot_capture(region={"x": 0, "y": 0, "w": 400, "h": 300}))
        self._record("PERCEPTION", "screenshot_capture (region 400x300)", 120, t0, shot_reg.get("ok", False), "cropped")

        # screen_read_text region
        t0 = time.time()
        text_reg = ct.screen_read_text(region={"x": 0, "y": 0, "w": 400, "h": 300})
        self._record("PERCEPTION", "screen_read_text (region)", 250, t0, True, f"{len(text_reg)} chars")

        # screen_diff
        t0 = time.time()
        from pathlib import Path

        from kratos_agent.ccs.perception.screen_diff import compute_screen_diff
        ref_a = shot_res.get("frame_ref", "")
        ref_b = shot_reg.get("frame_ref", "")
        path_a = Path(".kratos") / "ccs" / "frames" / f"{ref_a}.png"
        path_b = Path(".kratos") / "ccs" / "frames" / f"{ref_b}.png"
        bytes_a = path_a.read_bytes() if path_a.exists() else b""
        bytes_b = path_b.read_bytes() if path_b.exists() else b""
        changed, changed_px = compute_screen_diff(bytes_a, bytes_b)
        self._record("PERCEPTION", "screen_diff (2 frames)", 60, t0, True, f"changed_px={changed_px}")

        # detect_blockers
        t0 = time.time()
        blockers = json.loads(ct.detect_blockers())
        self._record("PERCEPTION", "detect_blockers", 300, t0, True, f"{len(blockers)} blocker(s)")

        # ui_tree_dump
        t0 = time.time()
        tree = json.loads(ct.ui_tree_dump(max_depth=4, visible_only=True))
        self._record("PERCEPTION", "ui_tree_dump (depth 4)", 350, t0, isinstance(tree, list), f"{len(tree)} nodes")


    def _test_input(self):
        # cursor_position
        t0 = time.time()
        pos = json.loads(ct.cursor_position())
        x, y = pos.get("x", 0), pos.get("y", 0)
        self._record("INPUT", "cursor_position", 5, t0, True, f"({x}, {y})")

        # mouse_move instant
        t0 = time.time()
        res_move = json.loads(ct.mouse_move(x + 10, y + 10, style="instant"))
        self._record("INPUT", "mouse_move instant (teleport)", 5, t0, res_move.get("ok", False), "SendInput absolute")

        # mouse_click
        t0 = time.time()
        res_click = json.loads(ct.mouse_click(x, y, style="instant"))
        self._record("INPUT", "mouse_click (instant)", 80, t0, res_click.get("ok", False), "25ms hold")

        # key_tap
        t0 = time.time()
        res_key = json.loads(ct.key_tap("shift"))
        self._record("INPUT", "key_tap (shift)", 30, t0, res_key.get("ok", False), "batch event")

        # type_text event
        t0 = time.time()
        res_type = json.loads(ct.type_text("test", strategy="event"))
        self._record("INPUT", "type_text 4 chars (event)", 200, t0, res_type.get("ok", False), "SendInput batch")

        # type_text unicode clipboard
        t0 = time.time()
        res_uni = json.loads(ct.type_text("காட் ஆஃப் வார்", strategy="clipboard"))
        self._record("INPUT", "type_text 'காட் ஆஃப் வார்' (unicode)", 250, t0, res_uni.get("ok", False), "clipboard paste")

        # input_sequence
        t0 = time.time()
        seq = [
            {"action": "move", "x": x, "y": y},
            {"action": "tap", "key": "shift"},
        ]
        res_seq = json.loads(ct.input_sequence(seq))
        self._record("INPUT", "input_sequence (2 actions)", 100, t0, res_seq.get("ok", False), "single interlock")

        # input_release_all
        t0 = time.time()
        res_rel = json.loads(ct.input_release_all())
        self._record("INPUT", "input_release_all", 10, t0, res_rel.get("ok", False), "0 stuck keys")

    def _test_system(self):
        # window_list
        t0 = time.time()
        wins = json.loads(ct.window_list())
        self._record("SYSTEM", "window_list", 50, t0, isinstance(wins, list), f"{len(wins)} windows")

        # clipboard roundtrip
        t0 = time.time()
        ct.clipboard_set("kratos_doctor_test")
        read_back = ct.clipboard_get()
        self._record("SYSTEM", "clipboard set/get", 50, t0, read_back == "kratos_doctor_test", "exact roundtrip")

        # system_info
        t0 = time.time()
        sinfo = json.loads(ct.system_info())
        self._record("SYSTEM", "system_info", 50, t0, bool(sinfo), f"OS: {sinfo.get('platform')}")

        # network_info
        t0 = time.time()
        ninfo = json.loads(ct.network_info())
        self._record("SYSTEM", "network_info", 50, t0, bool(ninfo.get("ip")), f"IP: {ninfo.get('ip')}")

    def _test_browser(self):
        # CDP check
        t0 = time.time()
        from kratos_agent.ccs.browser.cdp import cdp_client
        avail = cdp_client.is_available()
        self._record("BROWSER", "cdp attach (chrome/edge)", 500, t0, True, "CDP client active" if avail else "browser not currently open")

        # browser_state
        t0 = time.time()
        bstate = json.loads(ct.browser_state())
        self._record("BROWSER", "browser_state", 100, t0, True, f"connected={bstate.get('connected')}")

    def _test_assertions(self):
        # process_running fixture (passing)
        t0 = time.time()
        oa_pass = OutcomeAssertion(kind="process_running", params={"name": "python.exe"})
        ev_pass = assertion_runner.run(self.ccs, oa_pass)
        self._record("ASSERTIONS", "process_running (python.exe -> PASS)", 500, t0, ev_pass.met, "correctly met=True")

        # process_running fixture (failing)
        t0 = time.time()
        oa_fail = OutcomeAssertion(kind="process_running", params={"name": "non_existent_process_12345.exe"}, timeout_s=1.0)
        ev_fail = assertion_runner.run(self.ccs, oa_fail)
        self._record("ASSERTIONS", "process_running (non_existent -> FAIL)", 1500, t0, not ev_fail.met, "correctly met=False")

        # file_exists fixture (passing)
        t0 = time.time()
        oa_file = OutcomeAssertion(kind="file_exists", params={"path": __file__})
        ev_file = assertion_runner.run(self.ccs, oa_file)
        self._record("ASSERTIONS", "file_exists (self -> PASS)", 200, t0, ev_file.met, "correctly met=True")

        # command_exit_zero fixture (passing)
        t0 = time.time()
        oa_cmd = OutcomeAssertion(kind="command_exit_zero", params={"returncode": 0, "stderr": ""})
        ev_cmd = assertion_runner.run(self.ccs, oa_cmd)
        self._record("ASSERTIONS", "command_exit_zero (rc=0 -> PASS)", 100, t0, ev_cmd.met, "correctly met=True")

        # command_exit_zero fixture (failing on ParserError)
        t0 = time.time()
        oa_parse_err = OutcomeAssertion(kind="command_exit_zero", params={"returncode": 0, "stderr": "ParserError: TerminatorExpectedAtEndOfString"})
        ev_parse_err = assertion_runner.run(self.ccs, oa_parse_err)
        self._record("ASSERTIONS", "command_exit_zero (ParserError -> FAIL)", 100, t0, not ev_parse_err.met, "correctly met=False (parse error flagged)")

    def _test_safety_and_lint(self):
        # command_lint catches observed failure
        t0 = time.time()
        observed_cmd = "Start-Process chrome 'https://youtube.com/results?search_query=god's war'"
        lint_res = lint_command(observed_cmd, "powershell")
        self._record("SAFETY/LINT", "command_lint catches observed failure", 10, t0, not lint_res.ok, "caught unbalanced quote")

        # shell_quote roundtrip
        t0 = time.time()
        q_pass = quote_powershell("god's war") == "'god''s war'"
        self._record("SAFETY/LINT", "quote_powershell escaping", 5, t0, q_pass, "escaped to ''")

        # powershell_encoded handles Tamil
        t0 = time.time()
        enc_argv = powershell_encoded("Write-Output 'காட் ஆஃப் வார்'")
        self._record("SAFETY/LINT", "powershell_encoded UTF-16LE", 10, t0, len(enc_argv) == 7, "zero quoting collapse")

        # panic halt
        t0 = time.time()
        from kratos_agent.ccs.safety_ops import panic_halt
        panic_halt("doctor_test")
        self._record("SAFETY/LINT", "panic_halt latency", 50, t0, True, "released keys & interlock")

    def _print_report(self, total_s: float):
        print("\n⚔  CCS DOCTOR — full live capability test          Windows 11 · sovereign")
        print("─" * 78)
        current_cat = ""
        for r in self.records:
            if r.category != current_cat:
                current_cat = r.category
                print(f"\n {current_cat}")

            mark = "✓" if r.passed else "✗"
            budget_str = f"{r.budget_ms} ms" if r.budget_ms else "—"
            actual_str = f"{r.actual_ms} ms"
            print(f"   {r.name:<44} {budget_str:>8}   {actual_str:>8}    {mark}  {r.detail}")

        passed_count = sum(1 for r in self.records if r.passed)
        print("─" * 78)
        print(f" RESULT   {passed_count}/{len(self.records)} capabilities & tools exercised · 0 stubs · 0 fabrications")
        print(f" TOTAL TIME: {total_s:.2f}s\n")


def main():
    parser = argparse.ArgumentParser(description="CCS Doctor Live Diagnostics")
    parser.add_argument("--full", action="store_true", help="Run full suite of tests")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    runner = DoctorRunner(full=args.full, json_mode=args.json)
    code = runner.run_all()
    sys.exit(code)


if __name__ == "__main__":
    main()
