"""
DriftGuardian API.

OPEA-aligned pre-deployment governance gate for AI-generated KYC SOPs.

Endpoints:
  GET  /                  service info
  GET  /health            liveness
  GET  /sops              list SOP files in data/sop_drafts/  (legacy demo)
  POST /upload-policy     upload a PDF/DOCX/TXT/MD policy document
  POST /upload-sop        upload a PDF/DOCX/TXT/MD SOP draft
  POST /validate          run the validation pipeline

The validation pipeline accepts policy and SOP via:
  - filename (legacy: files under data/)
  - raw text (paste in)
  - doc_id   (returned from /upload-* endpoints)
"""
import logging
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from conformance_checker import compute_verdict, run_conformance_check
from dataprep import (
    get_uploaded_text,
    list_sop_files,
    load_global_baseline,
    load_regional_override,
    load_sop,
    store_upload,
)
from okr_extraction import extract_okr_fields
from remediation import generate_confluence_audit_log, generate_jira_ticket
from schemas import (
    UploadResponse,
    ValidationRequest,
    ValidationResult,
    Verdict,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("driftguardian")

app = FastAPI(
    title="DriftGuardian API",
    description="Pre-deployment governance gate for AI-generated KYC SOPs",
    version="1.1.0",
)

# CORS: env-configurable, defaults to localhost for safety.
_cors_origins = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:8080",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------- #
# Basic
# -------------------------------------------------------------- #
@app.get("/")
async def root():
    return {
        "service": "DriftGuardian",
        "status": "running",
        "version": app.version,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/sops")
async def list_sops():
    """List available SOP draft files in the demo data directory."""
    return {"sop_files": list_sop_files()}


# -------------------------------------------------------------- #
# Uploads
# -------------------------------------------------------------- #
async def _handle_upload(file: UploadFile) -> UploadResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        meta = await store_upload(file.filename or "upload", file.content_type or "", raw)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except RuntimeError as e:
        # Missing dependency (e.g. pypdf not installed)
        raise HTTPException(status_code=500, detail=str(e))
    return UploadResponse(**meta)


@app.post("/upload-policy", response_model=UploadResponse)
async def upload_policy(file: UploadFile = File(...)):
    """
    Upload a policy document (PDF, DOCX, TXT, MD, HTML).
    Returns a doc_id you can pass back as policy_doc_id in /validate.
    """
    return await _handle_upload(file)


@app.post("/upload-sop", response_model=UploadResponse)
async def upload_sop(file: UploadFile = File(...)):
    """
    Upload an SOP draft (PDF, DOCX, TXT, MD, HTML).
    Returns a doc_id you can pass back as sop_doc_id in /validate.
    """
    return await _handle_upload(file)


# -------------------------------------------------------------- #
# Validation pipeline
# -------------------------------------------------------------- #
def _resolve_text(
    *,
    filename: str | None,
    text: str | None,
    doc_id: str | None,
    role: str,
    loader,
) -> tuple[str, str]:
    """
    Resolve a (text, display_name) tuple from any of the three input modes.
    Raises HTTPException if nothing usable was provided.
    """
    if text and text.strip():
        return text, f"<inline {role}>"

    if doc_id:
        t = get_uploaded_text(doc_id)
        if not t:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown {role} doc_id: {doc_id}",
            )
        return t, f"<uploaded {role}:{doc_id}>"

    if filename:
        try:
            return loader(filename), filename
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))

    raise HTTPException(
        status_code=400,
        detail=(
            f"Provide one of {role}_filename, {role}_text, or {role}_doc_id."
        ),
    )


@app.post("/validate", response_model=ValidationResult)
async def validate_sop(request: ValidationRequest):
    """
    Validate an SOP draft against the policy hierarchy:
      1. Load policy (uploaded, inline, or built-in baseline)
      2. Load SOP
      3. Extract structured controls from both via the LLM
      4. Extract regional override controls (if available)
      5. Run conformance check
      6. Produce verdict + Jira/Confluence payloads
    """
    # ---- Policy ----
    if (
        request.policy_text
        or request.policy_doc_id
        or request.policy_filename
    ):
        policy_text, policy_name = _resolve_text(
            filename=request.policy_filename,
            text=request.policy_text,
            doc_id=request.policy_doc_id,
            role="policy",
            loader=lambda fn: open(fn, "r", encoding="utf-8").read(),
        )
    else:
        # legacy default: built-in baseline markdown
        try:
            policy_text = load_global_baseline()
            policy_name = "global_baseline_kyc_policy.md"
        except FileNotFoundError as e:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No policy provided and no built-in baseline found. "
                    "Upload one via /upload-policy or include policy_text."
                ),
            )

    # ---- SOP ----
    sop_text, sop_name = _resolve_text(
        filename=request.sop_filename,
        text=request.sop_text,
        doc_id=request.sop_doc_id,
        role="sop",
        loader=load_sop,
    )

    # ---- Regional override (legacy file lookup) ----
    regional_override_text = load_regional_override(request.region)

    # ---- Extract ----
    policy_fields = await extract_okr_fields(policy_text, policy_name)
    if not policy_fields:
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to extract controls from the policy document. "
                "Check that the LLM endpoint is reachable "
                f"(LLM_ENDPOINT={os.environ.get('LLM_ENDPOINT', 'default')})."
            ),
        )

    sop_fields = await extract_okr_fields(sop_text, sop_name)
    if not sop_fields:
        raise HTTPException(
            status_code=502,
            detail="Failed to extract controls from the SOP document.",
        )

    override_fields = []
    if regional_override_text:
        override_fields = await extract_okr_fields(
            regional_override_text, f"regional_override:{request.region}"
        )

    # ---- Check ----
    findings = run_conformance_check(policy_fields, sop_fields, override_fields)
    verdict = compute_verdict(findings)

    # ---- Enterprise payloads ----
    jira_payload = None
    confluence_payload = None
    if verdict in (Verdict.WARN, Verdict.BLOCK):
        jira_payload = generate_jira_ticket(sop_name, verdict, findings)
        confluence_payload = generate_confluence_audit_log(
            sop_name, verdict, findings, request.region
        )

    # ---- Summary ----
    if verdict == Verdict.PASS:
        summary = "SOP conforms to policy hierarchy. No unauthorized divergence detected."
    elif verdict == Verdict.WARN:
        summary = (
            f"{len(findings)} finding(s) detected. Changes match approved "
            f"regional overrides but require review before publishing."
        )
    else:
        block_count = sum(1 for f in findings if f.severity == Verdict.BLOCK)
        summary = (
            f"BLOCKED. {block_count} unauthorized policy divergence(s) detected. "
            f"SOP must not be published until findings are resolved."
        )

    return ValidationResult(
        verdict=verdict,
        sop_filename=sop_name,
        region=request.region,
        findings=findings,
        summary=summary,
        jira_payload=jira_payload,
        confluence_payload=confluence_payload,
    )