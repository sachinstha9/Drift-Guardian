from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from schemas import ValidationRequest, ValidationResult, Verdict
from dataprep import load_global_baseline, load_regional_override, load_sop, list_sop_files
from okr_extraction import extract_okr_fields
from conformance_checker import run_conformance_check, compute_verdict
from remediation import generate_jira_ticket, generate_confluence_audit_log

app = FastAPI(
    title="DriftGuardian API",
    description="Pre-deployment governance gate for AI-generated KYC SOPs",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"service": "DriftGuardian", "status": "running"}


@app.get("/sops")
async def list_sops():
    """List available SOP draft files."""
    return {"sop_files": list_sop_files()}


@app.post("/validate", response_model=ValidationResult)
async def validate_sop(request: ValidationRequest):
    """
    Full validation pipeline:
    1. Load policy hierarchy
    2. Load SOP draft
    3. Extract OKR fields from both via Qwen
    4. Run conformance check
    5. Generate verdict + payloads
    """

    # 1. Load documents
    try:
        global_policy_text = load_global_baseline()
        sop_text = load_sop(request.sop_filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    regional_override_text = load_regional_override(request.region)

    # 2. Extract OKR fields from global policy
    policy_fields = await extract_okr_fields(global_policy_text, "global_baseline")
    if not policy_fields:
        raise HTTPException(
            status_code=500,
            detail="Failed to extract fields from policy. Is Ollama running with qwen2.5:7b?"
        )

    # 3. Extract OKR fields from SOP
    sop_fields = await extract_okr_fields(sop_text, request.sop_filename)
    if not sop_fields:
        raise HTTPException(
            status_code=500,
            detail="Failed to extract fields from SOP. Is Ollama running with qwen2.5:7b?"
        )

    # 4. Extract regional override fields if available
    override_fields = []
    if regional_override_text:
        override_fields = await extract_okr_fields(regional_override_text, "regional_override")

    # 5. Run conformance check
    findings = run_conformance_check(policy_fields, sop_fields, override_fields)

    # 6. Compute verdict
    verdict = compute_verdict(findings)

    # 7. Generate enterprise payloads for WARN / BLOCK
    jira_payload = None
    confluence_payload = None
    if verdict in (Verdict.WARN, Verdict.BLOCK):
        jira_payload = generate_jira_ticket(request.sop_filename, verdict, findings)
        confluence_payload = generate_confluence_audit_log(
            request.sop_filename, verdict, findings, request.region
        )

    # 8. Build summary message
    if verdict == Verdict.PASS:
        summary = f"SOP conforms to policy hierarchy. No unauthorized divergence detected."
    elif verdict == Verdict.WARN:
        summary = (f"{len(findings)} finding(s) detected. Changes match approved regional "
                   f"overrides but require review before publishing.")
    else:
        block_count = sum(1 for f in findings if f.severity == Verdict.BLOCK)
        summary = (f"BLOCKED. {block_count} unauthorized policy divergence(s) detected. "
                   f"SOP must not be published until findings are resolved.")

    return ValidationResult(
        verdict=verdict,
        sop_filename=request.sop_filename,
        region=request.region,
        findings=findings,
        summary=summary,
        jira_payload=jira_payload,
        confluence_payload=confluence_payload
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
