"""
DriftGuardian — offline demo & evaluation runner.

Runs the full pipeline (mock extraction → conformance check → verdict) over
every case in data/ground_truth/case_manifest.json and compares the result to
the expected verdict, with zero external infrastructure.

Usage:
    LLM_MODE=mock python run_demo.py
    python run_demo.py            # defaults to mock mode automatically

Writes data/outputs/evaluation_metrics.json and a sample drift report.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

# Default to mock so the demo always runs.
os.environ.setdefault("LLM_MODE", "mock")

from conformance_checker import compute_verdict, run_conformance_check  # noqa: E402
from okr_extraction import extract_okr_fields  # noqa: E402
from remediation import generate_confluence_audit_log, generate_jira_ticket  # noqa: E402

HERE = Path(__file__).parent
POLICY_DIR = HERE / "data" / "policy_hierarchy"
SOP_DIR = HERE / "data" / "sop_drafts"
GT_DIR = HERE / "data" / "ground_truth"
OUT_DIR = HERE / "data" / "outputs"

# Which policy layer is the effective policy for each region (lightweight MVP:
# the regional override IS the effective policy; the calibration memo is docs).
EFFECTIVE_POLICY = {
    "APAC": "apac_override_policy.md",
    "EU": "eu_override_policy.md",
    "GLOBAL": "global_baseline_kyc_policy.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


async def run_case(case: dict) -> dict:
    region = case["region"].upper()
    policy_file = EFFECTIVE_POLICY.get(region, "global_baseline_kyc_policy.md")

    policy_text = _read(POLICY_DIR / policy_file)
    sop_text = _read(SOP_DIR / case["sop_file"])

    policy_fields = await extract_okr_fields(policy_text, source=policy_file)
    sop_fields = await extract_okr_fields(sop_text, source=case["sop_file"])
    # In the MVP the effective policy already encodes the approved variance,
    # so overrides == policy_fields (matching SOP to approved policy = PASS).
    override_fields = policy_fields

    findings = run_conformance_check(policy_fields, sop_fields, override_fields)
    verdict = compute_verdict(findings)

    return {
        "case_id": case["case_id"],
        "sop_file": case["sop_file"],
        "region": region,
        "expected": case["expected_verdict"],
        "actual": verdict.value,
        "match": verdict.value == case["expected_verdict"],
        "drift_types": sorted({f.drift_type.value for f in findings}),
        "findings": [f.model_dump() for f in findings],
        "verdict_obj": verdict,
    }


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(_read(GT_DIR / "case_manifest.json"))

    print(f"DriftGuardian demo — LLM_MODE={os.environ['LLM_MODE']}\n")
    print(f"{'case':10} {'region':7} {'expected':9} {'actual':9} drift")
    print("-" * 60)

    results = []
    correct = 0
    for case in manifest:
        r = await run_case(case)
        results.append(r)
        correct += r["match"]
        flag = "OK " if r["match"] else "XX "
        print(
            f"{r['case_id']:10} {r['region']:7} {r['expected']:9} "
            f"{r['actual']:9} {flag}{','.join(r['drift_types']) or '-'}"
        )

    total = len(results)
    acc = correct / total if total else 0.0
    print("-" * 60)
    print(f"verdict accuracy: {correct}/{total} = {acc:.0%}\n")

    # Write a sample drift report for the first BLOCK case (enterprise output).
    block_case = next((r for r in results if r["actual"] == "BLOCK"), None)
    if block_case:
        v = block_case["verdict_obj"]
        # rebuild DriftFinding objects for payload generators
        from schemas import DriftFinding

        findings = [DriftFinding(**f) for f in block_case["findings"]]
        (OUT_DIR / "sample_drift_report.json").write_text(
            json.dumps(
                {
                    "verdict": block_case["actual"],
                    "sop_file": block_case["sop_file"],
                    "region": block_case["region"],
                    "findings": block_case["findings"],
                },
                indent=2,
            )
        )
        (OUT_DIR / "sample_jira_ticket.json").write_text(
            json.dumps(generate_jira_ticket(block_case["sop_file"], v, findings), indent=2)
        )
        (OUT_DIR / "sample_confluence_audit_log.json").write_text(
            json.dumps(
                generate_confluence_audit_log(
                    block_case["sop_file"], v, findings, block_case["region"]
                ),
                indent=2,
            )
        )

    metrics = {
        "verdict_accuracy": acc,
        "cases_total": total,
        "cases_correct": correct,
        "per_case": [
            {k: r[k] for k in ("case_id", "expected", "actual", "match", "drift_types")}
            for r in results
        ],
    }
    (OUT_DIR / "evaluation_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"wrote {OUT_DIR}/evaluation_metrics.json + sample payloads")

    return 0 if correct == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
