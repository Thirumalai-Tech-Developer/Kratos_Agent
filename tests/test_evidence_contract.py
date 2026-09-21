from __future__ import annotations
import unittest
from kratos_agent.core.evidence import Evidence, OutcomeAssertion


class TestEvidenceContract(unittest.TestCase):
    def test_evidence_slots_and_trustworthy(self):
        ev = Evidence(
            claim="test claim",
            method="cdp_js",
            met=True,
            observed={"val": 42},
            confidence=1.0,
            samples=2,
            detail="All good",
            stale_ms=100,
        )
        self.assertTrue(ev.trustworthy)
        self.assertTrue(ev.met)
        self.assertEqual(ev.method, "cdp_js")

        # Stale evidence is not trustworthy
        ev_stale = Evidence(
            claim="stale claim",
            method="cdp_js",
            met=True,
            observed={},
            confidence=1.0,
            stale_ms=6000,
        )
        self.assertFalse(ev_stale.trustworthy)

        # Low confidence evidence is not trustworthy
        ev_low_conf = Evidence(
            claim="low conf",
            method="ocr",
            met=True,
            observed={},
            confidence=0.5,
            stale_ms=100,
        )
        self.assertFalse(ev_low_conf.trustworthy)

        # Unmet evidence is not trustworthy
        ev_unmet = Evidence(
            claim="unmet",
            method="cdp_js",
            met=False,
            observed={},
            confidence=1.0,
            stale_ms=100,
        )
        self.assertFalse(ev_unmet.trustworthy)

    def test_to_model_dict(self):
        ev = Evidence(
            claim="video is playing",
            method="cdp_js",
            met=True,
            observed={"currentTime": 4.2},
            confidence=0.954,
            samples=2,
            detail="playing at 4.2s",
            frame_ref="f123",
        )
        d = ev.to_model_dict()
        self.assertEqual(d["claim"], "video is playing")
        self.assertEqual(d["confidence"], 0.95)
        self.assertEqual(d["frame_ref"], "f123")
        self.assertEqual(d["observed"], {"currentTime": 4.2})

    def test_outcome_assertion_shape(self):
        oa = OutcomeAssertion(
            kind="media_playing",
            params={"selector": "video", "min_advance_s": 0.5},
            timeout_s=15.0,
            require_samples=2,
        )
        self.assertEqual(oa.kind, "media_playing")
        self.assertEqual(oa.require_samples, 2)
        self.assertEqual(oa.params["min_advance_s"], 0.5)


if __name__ == "__main__":
    unittest.main()
