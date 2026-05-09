from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class Verdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class DriftType(str, Enum):
    THRESHOLD_DRIFT = "threshold_drift"
    ROLE_DRIFT = "role_drift"
    TIME_WINDOW_DRIFT = "time_window_drift"
    STEP_OMISSION = "step_omission"
    REGION_MISMATCH = "region_mismatch"
    NO_DRIFT = "no_drift"


class OKRField(BaseModel):
    control_id: str
    trigger: Optional[str] = None
    threshold: Optional[str] = None
    required_actor: Optional[str] = None
    required_action: Optional[str] = None
    time_window: Optional[str] = None
    region: Optional[str] = None
    evidence_span: Optional[str] = None


class DriftFinding(BaseModel):
    control_id: str
    drift_type: DriftType
    expected: str
    observed: str
    evidence_span_policy: str
    evidence_span_sop: str
    severity: Verdict
    confidence: float
    remediation: str


class ValidationResult(BaseModel):
    verdict: Verdict
    sop_filename: str
    region: str
    findings: List[DriftFinding]
    summary: str
    jira_payload: Optional[dict] = None
    confluence_payload: Optional[dict] = None


class ValidationRequest(BaseModel):
    sop_filename: str
    region: str = "APAC"
