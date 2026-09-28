from kratos_agent.core.evidence import Evidence
from kratos_agent.core.verification_manager import VerificationManager


def test_browser_usage_without_live_outcome_evidence_does_not_pass(tmp_path):
    result = VerificationManager(tmp_path).verify_workspace(
        [], verification_type="browser", require_files=False, browser_evidence=[]
    )

    assert result.passed is False
    assert result.browser_passed is False
    assert "no passing live assertion evidence" in result.summary.lower() or any(
        "no passing live assertion evidence" in item.lower() for item in result.details
    )


def test_browser_verification_accepts_trustworthy_observed_assertion(tmp_path):
    evidence = Evidence(
        claim="page title matches Kratos",
        method="cdp_js",
        met=True,
        observed={"title": "Kratos"},
        detail="Page title: Kratos",
    )
    result = VerificationManager(tmp_path).verify_workspace(
        [], verification_type="browser", require_files=False, browser_evidence=[evidence]
    )

    assert result.passed is True
    assert result.browser_passed is True
