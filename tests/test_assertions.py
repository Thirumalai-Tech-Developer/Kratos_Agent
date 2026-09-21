from __future__ import annotations
import tempfile
import os
import unittest
from kratos_agent.ccs.assertions import assertion_runner
from kratos_agent.core.evidence import OutcomeAssertion


class FakeCCS:
    def __init__(self):
        self.cdp_responses = []
        self.screen_text = ""
        self.elements = {}
        self.windows = []
        self.last_command_result = {}
        self.screen_diff_pixels = 100

    def eval_cdp(self, script: str):
        if self.cdp_responses:
            return self.cdp_responses.pop(0)
        return None

    def read_screen_text(self):
        return self.screen_text

    def find_element(self, query, app=None, role=None):
        return self.elements.get(query)

    def list_windows(self):
        return self.windows

    def get_last_screen_diff_pixels(self):
        return self.screen_diff_pixels


class TestAssertions(unittest.TestCase):
    def setUp(self):
        self.ccs = FakeCCS()

    def test_media_playing_pass_and_fail(self):
        # Passing: video found, paused=False, advancing
        self.ccs.cdp_responses = [
            {"found": True, "paused": False, "ended": False, "readyState": 3, "videoWidth": 1920, "currentTime": 1.0},
            {"found": True, "paused": False, "ended": False, "readyState": 3, "videoWidth": 1920, "currentTime": 2.5},
        ]
        ast = OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}, timeout_s=1.0, sample_gap_ms=100)
        ev = assertion_runner.run(self.ccs, ast)
        self.assertTrue(ev.met)
        self.assertEqual(ev.method, "cdp_js")

        # Failing: video paused / currentTime not advancing
        self.ccs.cdp_responses = [
            {"found": True, "paused": True, "ended": False, "readyState": 3, "videoWidth": 1920, "currentTime": 0.0},
        ]
        ast_fail = OutcomeAssertion(kind="media_playing", params={"min_advance_s": 0.5}, timeout_s=0.2, poll_ms=50)
        ev_fail = assertion_runner.run(self.ccs, ast_fail)
        self.assertFalse(ev_fail.met)

    def test_url_matches_pass_and_fail(self):
        self.ccs.cdp_responses = ["https://www.youtube.com/watch?v=123"]
        ast = OutcomeAssertion(kind="url_matches", params={"pattern": r"youtube\.com/watch"}, timeout_s=0.2)
        ev = assertion_runner.run(self.ccs, ast)
        self.assertTrue(ev.met)

        self.ccs.cdp_responses = ["https://www.google.com/"]
        ast_fail = OutcomeAssertion(kind="url_matches", params={"pattern": r"youtube\.com/watch"}, timeout_s=0.2, poll_ms=50)
        ev_fail = assertion_runner.run(self.ccs, ast_fail)
        self.assertFalse(ev_fail.met)

    def test_text_visible_and_absent(self):
        self.ccs.screen_text = "Search YouTube Videos God of War"
        ast_vis = OutcomeAssertion(kind="text_visible", params={"text": "God of War"}, timeout_s=0.2)
        ev_vis = assertion_runner.run(self.ccs, ast_vis)
        self.assertTrue(ev_vis.met)

        ast_abs = OutcomeAssertion(kind="text_absent", params={"text": "Sign in to confirm"}, timeout_s=0.2)
        ev_abs = assertion_runner.run(self.ccs, ast_abs)
        self.assertTrue(ev_abs.met)

        ast_abs_fail = OutcomeAssertion(kind="text_absent", params={"text": "YouTube"}, timeout_s=0.2)
        ev_abs_fail = assertion_runner.run(self.ccs, ast_abs_fail)
        self.assertFalse(ev_abs_fail.met)

    def test_window_exists_pass_and_fail(self):
        class FakeWin:
            def __init__(self, title, is_active=False):
                self.title = title
                self.is_active = is_active
                self.app_name = "chrome"

        self.ccs.windows = [FakeWin("YouTube - Google Chrome", True)]
        ast = OutcomeAssertion(kind="window_exists", params={"title_pattern": "YouTube"}, timeout_s=0.2)
        ev = assertion_runner.run(self.ccs, ast)
        self.assertTrue(ev.met)

        ast_fail = OutcomeAssertion(kind="window_exists", params={"title_pattern": "Calculator"}, timeout_s=0.2, poll_ms=50)
        ev_fail = assertion_runner.run(self.ccs, ast_fail)
        self.assertFalse(ev_fail.met)

    def test_file_exists_and_content_matches(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tf:
            tf.write("God of War Ragnarok 2026")
            tf_path = tf.name

        try:
            ast_f = OutcomeAssertion(kind="file_exists", params={"path": tf_path, "min_bytes": 5}, timeout_s=0.2)
            ev_f = assertion_runner.run(self.ccs, ast_f)
            self.assertTrue(ev_f.met)

            ast_c = OutcomeAssertion(kind="file_content_matches", params={"path": tf_path, "pattern": "Ragnarok"}, timeout_s=0.2)
            ev_c = assertion_runner.run(self.ccs, ast_c)
            self.assertTrue(ev_c.met)

            ast_cfail = OutcomeAssertion(kind="file_content_matches", params={"path": tf_path, "pattern": "Mario"}, timeout_s=0.2)
            ev_cfail = assertion_runner.run(self.ccs, ast_cfail)
            self.assertFalse(ev_cfail.met)
        finally:
            os.remove(tf_path)

    def test_composite_assertion(self):
        self.ccs.screen_text = "God of War"
        self.ccs.cdp_responses = ["https://www.youtube.com/watch?v=xyz"]

        ast_comp = OutcomeAssertion(
            kind="composite",
            params={
                "all_of": [
                    {"kind": "text_visible", "params": {"text": "God of War"}},
                    {"kind": "url_matches", "params": {"pattern": "youtube\\.com"}},
                ]
            },
            timeout_s=0.2,
        )
        ev = assertion_runner.run(self.ccs, ast_comp)
        self.assertTrue(ev.met)


if __name__ == "__main__":
    unittest.main()
