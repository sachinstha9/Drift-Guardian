"""
Offline, deterministic control-field extractor.

Used when LLM_MODE=mock (or no LLM endpoint is reachable) so the demo runs
end-to-end with zero infrastructure. It parses the structured "Control Fields"
block that every policy/SOP in this benchmark includes, plus a few inline
patterns, and returns the same OKRField objects the LLM path would.

This is intentionally simple: it relies on the consistent document structure
recommended in the project design (every SOP ends with a Control Fields list).
"""
from __future__ import annotations

import re
from typing import List, Optional

from schemas import OKRField

_FIELD_ALIASES = {
    "control id": "control_id",
    "trigger": "trigger",
    "threshold": "threshold",
    "required actor": "required_actor",
    "required action": "required_action",
    "time window": "time_window",
    "region": "region",
    "gating requirement": "gating_requirement",  # not an OKRField; kept for evidence
}

_TIME_UNIT_HOURS = {
    "hour": 1.0,
    "hours": 1.0,
    "day": 24.0,
    "days": 24.0,
    "business day": 24.0,
    "business days": 24.0,
    "week": 168.0,
    "weeks": 168.0,
    "month": 730.0,
    "months": 730.0,
    "year": 8760.0,
    "years": 8760.0,
}


def _parse_threshold_value(text: Optional[str]) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """Return (value, operator, unit) from a string like 'risk_score >= 85'."""
    if not text:
        return None, None, None
    m = re.search(r"([a-zA-Z_][\w ]*?)\s*(>=|<=|==|>|<)\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not m:
        return None, None, None
    unit = m.group(1).strip().replace(" ", "_") or None
    operator = m.group(2)
    value = float(m.group(3))
    return value, operator, unit


def _parse_time_window_hours(text: Optional[str]) -> Optional[float]:
    """Return hours from 'within 24 hours', 'three business days', etc."""
    if not text:
        return None
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    t = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(business day|business days|hours|hour|days|day|weeks|week|months|month|years|year)", t)
    if not m:
        m2 = re.search(r"\b(" + "|".join(words) + r")\s+(business day|business days|hours|hour|days|day|weeks|week)", t)
        if not m2:
            return None
        qty = float(words[m2.group(1)])
        unit = m2.group(2)
    else:
        qty = float(m.group(1))
        unit = m.group(2)
    return qty * _TIME_UNIT_HOURS.get(unit, 1.0)


def _extract_control_blocks(text: str) -> List[dict]:
    """
    Find every '## ... Control Fields' bullet list (or '### Control:' block) and
    parse its 'Key: value' lines.
    """
    blocks: List[dict] = []
    # Split on lines that introduce a control fields list.
    # Strategy: scan line by line, collect bullet 'Key: value' pairs into the
    # current block; a new block starts at a header containing 'Control'.
    current: dict = {}
    current_evidence: List[str] = []

    def flush():
        if current.get("control_id"):
            current["__evidence"] = " ".join(current_evidence).strip()
            blocks.append(dict(current))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        # bullet of form "- Key: value" or "**Key:** value"
        bm = re.match(r"^[-*]\s*\*{0,2}([A-Za-z ]+?)\*{0,2}\s*:\s*(.+)$", line)
        if bm:
            key = bm.group(1).strip().lower()
            val = bm.group(2).strip().strip("*").strip()
            field = _FIELD_ALIASES.get(key)
            if field == "control_id":
                # new control begins
                flush()
                current = {"control_id": val}
                current_evidence = [line]
            elif field:
                current[field] = val
                current_evidence.append(line)
            continue
        # capture nearby prose as evidence if we're inside a block
        if current and line:
            current_evidence.append(line)

    flush()
    return blocks


def extract_okr_fields_mock(text: str, source: str = "") -> List[OKRField]:
    """Deterministic offline extraction. Mirrors extract_okr_fields' contract."""
    if not text or not text.strip():
        return []

    fields: List[OKRField] = []
    for blk in _extract_control_blocks(text):
        threshold = blk.get("threshold")
        tv, op, unit = _parse_threshold_value(threshold)
        twh = _parse_time_window_hours(blk.get("time_window"))
        evidence = blk.get("__evidence") or threshold or blk["control_id"]

        fields.append(
            OKRField(
                control_id=blk["control_id"],
                trigger=blk.get("trigger"),
                threshold=threshold,
                threshold_value=tv,
                threshold_operator=op,
                threshold_unit=unit,
                time_window=blk.get("time_window"),
                time_window_hours=twh,
                required_actor=blk.get("required_actor"),
                required_action=blk.get("required_action"),
                region=blk.get("region"),
                evidence_span=evidence[:600],
            )
        )
    return fields
