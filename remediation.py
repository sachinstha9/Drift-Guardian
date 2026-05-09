from typing import List
from datetime import datetime
from schemas import DriftFinding, Verdict


def generate_jira_ticket(
    sop_filename: str,
    verdict: Verdict,
    findings: List[DriftFinding]
) -> dict:
    """Generate a realistic Jira REST API payload for remediation."""
    if not findings:
        return {}

    drift_summary = "; ".join(
        f"{f.drift_type.value} in {f.control_id}" for f in findings
    )

    description_lines = [
        f"DriftGuardian detected unauthorized policy divergence in: *{sop_filename}*\n",
        "*Detected Issues:*"
    ]
    for f in findings:
        description_lines.append(
            f"- [{f.severity.value}] {f.drift_type.value.replace('_', ' ').title()} "
            f"in {f.control_id}\n"
            f"  Expected: {f.expected}\n"
            f"  Observed: {f.observed}\n"
            f"  Remediation: {f.remediation}"
        )

    return {
        "fields": {
            "project": {"key": "COMP"},
            "summary": f"[DriftGuardian] {verdict.value}: Unauthorized policy divergence in {sop_filename}",
            "description": "\n".join(description_lines),
            "issuetype": {"name": "Compliance Task"},
            "priority": {"name": "High" if verdict == Verdict.BLOCK else "Medium"},
            "labels": ["driftguardian", "kyc-governance", verdict.value.lower()],
            "customfield_drift_types": [f.drift_type.value for f in findings],
            "customfield_sop_file": sop_filename,
            "customfield_detected_at": datetime.utcnow().isoformat() + "Z"
        }
    }


def generate_confluence_audit_log(
    sop_filename: str,
    verdict: Verdict,
    findings: List[DriftFinding],
    region: str
) -> dict:
    """Generate a Confluence REST API page payload as audit log."""
    timestamp = datetime.utcnow().isoformat() + "Z"

    rows = ""
    for f in findings:
        rows += (
            f"<tr>"
            f"<td>{f.control_id}</td>"
            f"<td>{f.drift_type.value.replace('_', ' ').title()}</td>"
            f"<td>{f.expected}</td>"
            f"<td>{f.observed}</td>"
            f"<td><strong>{f.severity.value}</strong></td>"
            f"<td>{f.remediation}</td>"
            f"</tr>"
        )

    table = f"""
<table>
  <thead>
    <tr>
      <th>Control ID</th><th>Drift Type</th><th>Expected</th>
      <th>Observed</th><th>Severity</th><th>Remediation</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
""" if findings else "<p>No drift findings detected.</p>"

    body = f"""
<h2>DriftGuardian Audit Log</h2>
<p><strong>SOP File:</strong> {sop_filename}</p>
<p><strong>Region:</strong> {region}</p>
<p><strong>Validated At:</strong> {timestamp}</p>
<p><strong>Overall Verdict:</strong> {verdict.value}</p>
<h3>Findings</h3>
{table}
"""

    return {
        "type": "page",
        "title": f"[DriftGuardian Audit] {sop_filename} — {timestamp[:10]}",
        "space": {"key": "COMP"},
        "body": {
            "storage": {
                "value": body,
                "representation": "storage"
            }
        },
        "metadata": {
            "labels": [
                {"name": "driftguardian"},
                {"name": "kyc-audit"},
                {"name": verdict.value.lower()}
            ]
        }
    }
