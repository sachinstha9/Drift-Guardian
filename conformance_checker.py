from typing import List, Tuple
from schemas import OKRField, DriftFinding, DriftType, Verdict
import re


def normalise(text: str) -> str:
    """Lowercase and strip for loose comparison."""
    if not text:
        return ""
    return text.lower().strip()


def extract_number(text: str) -> float | None:
    """Pull first number from a string like 'risk_score >= 90'."""
    if not text:
        return None
    nums = re.findall(r'\d+\.?\d*', text)
    return float(nums[0]) if nums else None


def extract_hours(text: str) -> float | None:
    """Convert time expressions to hours. 'within 24 hours' -> 24, 'within 3 days' -> 72."""
    if not text:
        return None
    text = text.lower()
    num_match = re.findall(r'\d+\.?\d*', text)
    if not num_match:
        return None
    num = float(num_match[0])
    if 'day' in text:
        return num * 24
    return num


def check_threshold(policy_field: OKRField, sop_field: OKRField) -> DriftFinding | None:
    """Detect unauthorized threshold changes."""
    p_thresh = policy_field.threshold
    s_thresh = sop_field.threshold

    if not p_thresh or not s_thresh:
        return None

    p_num = extract_number(p_thresh)
    s_num = extract_number(s_thresh)

    if p_num is None or s_num is None:
        return None

    if p_num != s_num:
        return DriftFinding(
            control_id=policy_field.control_id,
            drift_type=DriftType.THRESHOLD_DRIFT,
            expected=p_thresh,
            observed=s_thresh,
            evidence_span_policy=policy_field.evidence_span or p_thresh,
            evidence_span_sop=sop_field.evidence_span or s_thresh,
            severity=Verdict.BLOCK,
            confidence=0.95,
            remediation=f"Restore threshold to '{p_thresh}' or attach an approved regional override."
        )
    return None


def check_role(policy_field: OKRField, sop_field: OKRField) -> DriftFinding | None:
    """Detect unauthorized role changes."""
    p_actor = normalise(policy_field.required_actor or "")
    s_actor = normalise(sop_field.required_actor or "")

    if not p_actor or not s_actor:
        return None

    if p_actor != s_actor:
        return DriftFinding(
            control_id=policy_field.control_id,
            drift_type=DriftType.ROLE_DRIFT,
            expected=policy_field.required_actor,
            observed=sop_field.required_actor,
            evidence_span_policy=policy_field.evidence_span or policy_field.required_actor,
            evidence_span_sop=sop_field.evidence_span or sop_field.required_actor,
            severity=Verdict.BLOCK,
            confidence=0.92,
            remediation=f"Restore responsible actor to '{policy_field.required_actor}'."
        )
    return None


def check_time_window(policy_field: OKRField, sop_field: OKRField) -> DriftFinding | None:
    """Detect unauthorized time window changes."""
    p_time = policy_field.time_window
    s_time = sop_field.time_window

    if not p_time or not s_time:
        return None

    p_hours = extract_hours(p_time)
    s_hours = extract_hours(s_time)

    if p_hours is None or s_hours is None:
        return None

    if s_hours > p_hours:
        # longer time window = weaker control = BLOCK
        severity = Verdict.BLOCK
    elif s_hours < p_hours:
        # stricter is a WARN - tighter but not approved
        severity = Verdict.WARN
    else:
        return None

    return DriftFinding(
        control_id=policy_field.control_id,
        drift_type=DriftType.TIME_WINDOW_DRIFT,
        expected=p_time,
        observed=s_time,
        evidence_span_policy=policy_field.evidence_span or p_time,
        evidence_span_sop=sop_field.evidence_span or s_time,
        severity=severity,
        confidence=0.90,
        remediation=f"Restore time window to '{p_time}'."
    )


def match_sop_to_policy(
    policy_fields: List[OKRField],
    sop_fields: List[OKRField]
) -> List[Tuple[OKRField, OKRField]]:
    """Match SOP control fields to their corresponding policy fields by control_id."""
    matches = []
    policy_map = {normalise(f.control_id): f for f in policy_fields}

    for sop_f in sop_fields:
        key = normalise(sop_f.control_id)
        if key in policy_map:
            matches.append((policy_map[key], sop_f))
        else:
            # fuzzy match - try partial control_id overlap
            for p_key, p_field in policy_map.items():
                if key in p_key or p_key in key:
                    matches.append((p_field, sop_f))
                    break

    return matches


def apply_regional_override(
    finding: DriftFinding,
    override_fields: List[OKRField]
) -> bool:
    """
    Returns True if the finding is covered by an approved regional override.
    If True, the finding should be downgraded from BLOCK to WARN or dropped.
    """
    for ov in override_fields:
        if normalise(ov.control_id) != normalise(finding.control_id):
            continue

        if finding.drift_type == DriftType.THRESHOLD_DRIFT:
            ov_num = extract_number(ov.threshold or "")
            obs_num = extract_number(finding.observed)
            if ov_num and obs_num and ov_num == obs_num:
                return True

        if finding.drift_type == DriftType.TIME_WINDOW_DRIFT:
            ov_h = extract_hours(ov.time_window or "")
            obs_h = extract_hours(finding.observed)
            if ov_h and obs_h and ov_h == obs_h:
                return True

    return False


def run_conformance_check(
    policy_fields: List[OKRField],
    sop_fields: List[OKRField],
    override_fields: List[OKRField] = None
) -> List[DriftFinding]:
    """
    Core conformance logic.
    Compares SOP fields against policy fields.
    Applies regional overrides where applicable.
    Returns only findings with evidence spans.
    """
    override_fields = override_fields or []
    findings = []

    matched_pairs = match_sop_to_policy(policy_fields, sop_fields)

    for policy_f, sop_f in matched_pairs:
        # run all checkers
        checks = [
            check_threshold(policy_f, sop_f),
            check_role(policy_f, sop_f),
            check_time_window(policy_f, sop_f),
        ]

        for finding in checks:
            if finding is None:
                continue

            # validate - must have both evidence spans
            if not finding.evidence_span_policy or not finding.evidence_span_sop:
                continue
            if finding.confidence < 0.4:
                continue

            # check if covered by approved regional override
            if apply_regional_override(finding, override_fields):
                # downgrade to WARN - it changed but it's authorized
                finding.severity = Verdict.WARN
                finding.remediation = "Change matches approved regional override. Attach override reference."

            findings.append(finding)

    return findings


def compute_verdict(findings: List[DriftFinding]) -> Verdict:
    """Derive overall verdict from list of findings."""
    if not findings:
        return Verdict.PASS
    severities = [f.severity for f in findings]
    if Verdict.BLOCK in severities:
        return Verdict.BLOCK
    if Verdict.WARN in severities:
        return Verdict.WARN
    return Verdict.PASS
