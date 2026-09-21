import unittest
from kratos_agent.ccs.perception.blockers import (
    Blocker,
    detect_blockers,
    clear_blocker,
    get_blocker_by_name,
)

class MockCCS:
    def __init__(self, cdp_responses=None, ocr_text=""):
        self.cdp_responses = cdp_responses or {}
        self.ocr_text = ocr_text

    def browser_js(self, script: str):
        for k, v in self.cdp_responses.items():
            if k in script:
                return {"value": v}
        return {"value": False}

    def screen_read_text(self, frame_ref=None):
        return self.ocr_text

    def browser_click(self, **kwargs):
        pass

    def key_tap(self, key):
        pass

class TestBlockers(unittest.TestCase):
    def test_detect_cookie_consent_via_cdp(self):
        ccs = MockCCS(cdp_responses={"tp-yt-paper-dialog": True})
        blockers = detect_blockers(ccs)
        names = [b.name for b in blockers]
        self.assertIn("cookie_consent", names)

    def test_detect_youtube_bot_wall_via_cdp(self):
        ccs = MockCCS(cdp_responses={"sign in to confirm": True})
        blockers = detect_blockers(ccs)
        names = [b.name for b in blockers]
        self.assertIn("youtube_bot_wall", names)
        # Verify it is not clearable
        wall = next(b for b in blockers if b.name == "youtube_bot_wall")
        self.assertFalse(wall.clearable)

    def test_detect_via_ocr_fallback(self):
        ccs = MockCCS(ocr_text="Please Accept All Cookies to continue to YouTube")
        blockers = detect_blockers(ccs)
        names = [b.name for b in blockers]
        self.assertIn("cookie_consent", names)

    def test_detect_bot_wall_via_ocr(self):
        ccs = MockCCS(ocr_text="Sign in to confirm you're not a robot")
        blockers = detect_blockers(ccs)
        names = [b.name for b in blockers]
        self.assertIn("youtube_bot_wall", names)

    def test_clear_blocker_uncool_bot_wall_fails_honestly(self):
        ccs = MockCCS()
        evidence = clear_blocker(ccs, "youtube_bot_wall")
        self.assertFalse(evidence.met)
        self.assertIn("sign-in wall", evidence.detail)

    def test_clear_cookie_consent_success(self):
        ccs = MockCCS(cdp_responses={"Accept": False}) # probe returns False after clear
        evidence = clear_blocker(ccs, "cookie_consent")
        self.assertTrue(evidence.met)
        self.assertIn("cleared successfully", evidence.detail)

if __name__ == "__main__":
    unittest.main()
