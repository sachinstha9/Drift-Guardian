"""
Conformance checker unit tests.

These exercise the matching + check logic directly (no LLM calls) by
feeding pre-built OKRField objects. They cover the three verdict paths
the demo needs to land cleanly.
"""
import sys
from pathlib import Path

# Make the app/ package importable when running pytest from repo root.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "app"))

from conformance_checker import (  # noqa: E402
    apply_regional_override,
    compute_verdict,
    match_sop_to_policy,
    run_conformance_check,
)
from schemas import DriftType, OKRField, Verdict  # noqa: E402


def _policy_high_risk_review() -> OKRField:
    return OKRField(
        control_id="KYC_HIGH_RISK_REVIEW",
        trigger="customer onboarding",
        threshold="risk_score >= 80",
        threshold_value=80.0,
        threshold_operator=">=",
        threshold_unit="risk_score",
        required_actor="L2 Compliance Analyst",
        required_action="Escalate for enhanced due diligence review",
        time_window="within 24 hours",
        time_window_hours=24.0,
        region="GLOBAL",
        evidence_span=(
            "Customers with a risk_score >= 80 must be escalated to "
            "an L2 Compliance Analyst within 24 hours for enhanced "
            "due diligence."
        ),
    )


def test_pass_when_sop_matches_policy():
    policy = [_policy_high_risk_review()]
    sop = [_policy_high_risk_review()]  # identical
    findings = run_conformance_check(policy, sop, override_fields=[])
    assert findings == []
    assert compute_verdict(findings) == Verdict.PASS


def test_block_on_threshold_drift():
    policy = [_policy_high_risk_review()]
    sop_field = _policy_high_risk_review()
    # SOP raised the threshold — fewer customers reviewed = weaker control
    sop_field.threshold = "risk_score >= 90"
    sop_field.threshold_value = 90.0
    sop_field.evidence_span = (
        "Customers with a risk_score of 90 or higher must be reviewed."
    )
    findings = run_conformance_check(policy, [sop_field], override_fields=[])
    assert len(findings) == 1
    assert findings[0].drift_type == DriftType.THRESHOLD_DRIFT
    assert findings[0].severity == Verdict.BLOCK
    assert compute_verdict(findings) == Verdict.BLOCK


def test_warn_when_threshold_drift_matches_regional_override():
    policy = [_policy_high_risk_review()]
    sop_field = _policy_high_risk_review()
    sop_field.threshold = "risk_score >= 70"
    sop_field.threshold_value = 70.0
    sop_field.region = "APAC"
    sop_field.evidence_span = "APAC customers reviewed at risk_score >= 70."

    # Approved APAC override allows risk_score >= 70.
    override = OKRField(
        control_id="KYC_HIGH_RISK_REVIEW",
        threshold="risk_score >= 70",
        threshold_value=70.0,
        threshold_operator=">=",
        threshold_unit="risk_score",
        region="APAC",
        evidence_span="APAC regional override: review threshold is 70.",
    )

    findings = run_conformance_check(policy, [sop_field], override_fields=[override])
    assert len(findings) == 1
    assert findings[0].severity == Verdict.WARN, (
        "Override should downgrade BLOCK to WARN"
    )
    assert compute_verdict(findings) == Verdict.WARN


def test_block_on_time_window_loosening():
    policy = [_policy_high_risk_review()]
    sop_field = _policy_high_risk_review()
    sop_field.time_window = "within 3 business days"
    sop_field.time_window_hours = 72.0  # vs policy 24 — looser = BLOCK
    sop_field.evidence_span = "Review within 3 business days."
    findings = run_conformance_check(policy, [sop_field], override_fields=[])
    assert any(
        f.drift_type == DriftType.TIME_WINDOW_DRIFT and f.severity == Verdict.BLOCK
        for f in findings
    )


def test_warn_on_time_window_tightening():
    policy = [_policy_high_risk_review()]
    sop_field = _policy_high_risk_review()
    sop_field.time_window = "within 4 hours"
    sop_field.time_window_hours = 4.0  # stricter than policy = WARN
    sop_field.evidence_span = "Review within 4 hours."
    findings = run_conformance_check(policy, [sop_field], override_fields=[])
    assert any(
        f.drift_type == DriftType.TIME_WINDOW_DRIFT and f.severity == Verdict.WARN
        for f in findings
    )


def test_role_drift_blocked_but_close_wording_ignored():
    """Same role spelled differently should NOT BLOCK; a real role change should."""
    policy = [_policy_high_risk_review()]

    # Same role, slightly different wording -> should not flag (rapidfuzz)
    sop_close = _policy_high_risk_review()
    sop_close.required_actor = "L2 Compliance Analyst."  # trailing period
    findings = run_conformance_check(policy, [sop_close], override_fields=[])
    assert not any(f.drift_type == DriftType.ROLE_DRIFT for f in findings)

    # Actually different role -> BLOCK
    sop_far = _policy_high_risk_review()
    sop_far.required_actor = "Junior Operations Clerk"
    findings = run_conformance_check(policy, [sop_far], override_fields=[])
    assert any(
        f.drift_type == DriftType.ROLE_DRIFT and f.severity == Verdict.BLOCK
        for f in findings
    )


def test_matcher_prefers_same_region_over_global():
    """When two policy controls share an ID, region should be the tiebreaker."""
    global_ctrl = _policy_high_risk_review()
    global_ctrl.region = "GLOBAL"
    global_ctrl.threshold_value = 80.0

    apac_ctrl = _policy_high_risk_review()
    apac_ctrl.region = "APAC"
    apac_ctrl.threshold_value = 70.0

    sop = _policy_high_risk_review()
    sop.region = "APAC"
    sop.threshold_value = 70.0  # matches APAC, not GLOBAL

    matches = match_sop_to_policy([global_ctrl, apac_ctrl], [sop])
    assert len(matches) == 1
    chosen_policy, _ = matches[0]
    assert chosen_policy.region == "APAC", (
        "Matcher should prefer same-region policy over GLOBAL"
    )


def test_override_with_zero_threshold_is_not_dropped():
    """Regression test for the 'if ov_num and obs_num' truthiness bug."""
    policy_field = _policy_high_risk_review()
    policy_field.threshold_value = 1.0  # policy says >= 1

    sop_field = _policy_high_risk_review()
    sop_field.threshold = "risk_score >= 0"
    sop_field.threshold_value = 0.0  # SOP says >= 0
    sop_field.evidence_span = "All customers reviewed (risk_score >= 0)."

    override = OKRField(
        control_id="KYC_HIGH_RISK_REVIEW",
        threshold="risk_score >= 0",
        threshold_value=0.0,
        region="APAC",
        evidence_span="APAC reviews all customers regardless of score.",
    )

    findings = run_conformance_check(
        [policy_field], [sop_field], override_fields=[override]
    )
    # The threshold drift should be detected AND downgraded by the override.
    assert len(findings) == 1
    assert findings[0].severity == Verdict.WARN, (
        "Override with threshold_value=0 was incorrectly treated as falsy"
    )