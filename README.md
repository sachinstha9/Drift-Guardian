# DriftGuardian

**A governance gate for AI-drafted compliance SOPs.**

DriftGuardian detects *unauthorized policy divergence* between AI-generated KYC
Standard Operating Procedures (SOPs) and an approved policy hierarchy — threshold
tampering, role swaps, time-window creep, and removed control steps — before the
document reaches production.

The system does **not** flag every textual difference. It detects whether an
AI-generated SOP has deviated from the approved policy hierarchy *without
authorization*. A difference is acceptable only when it is supported by an
approved regional override.

---

## Why this matters

The four pillars of CDD defined by the Basel Committee (2001) — customer
acceptance policy, identification, ongoing monitoring of high-risk accounts, and
risk management — together with FATF Recommendation 10, form the foundation of
DriftGuardian's baseline policy hierarchy. DriftGuardian validates whether
AI-generated SOPs remain conformant with these established control points.

Real-world relevance: recent FCA enforcement actions against UK banks for AML
systems-and-controls failings underline why drift in operational compliance
procedures carries material risk.

---

## Four-level evidence chain

```
Level 1  International principles   FATF R.10, Basel CDD, AMLA draft RTS
   ↓                                (provide risk-based logic, NOT thresholds)
Level 2  Regional context          APAC / EU regulatory expectations
   ↓
Level 3  Internal calibration      apac_regional_risk_calibration_memo.md
   ↓                                (synthetic memo that APPROVES risk_score >= 85)
Level 4  AI-generated SOP draft     data/sop_drafts/*.md
   ↓
DriftGuardian → PASS / WARN / BLOCK
```

**The threshold of 85 is not a regulatory figure.** It is a synthetic internal
calibration decision created for this prototype under the risk-based approach.
FATF / Basel / AMLA support risk-based calibration; they do not authorize a
specific number.

### Decision logic

- SOP matches the approved policy layer → **PASS**
- SOP differs but the difference is a documented/approved override → **WARN**
- SOP differs with no authorization → **BLOCK**

For APAC: baseline threshold is 80; the approved APAC override formalizes 85. An
SOP at `>= 85` passes; an SOP at `>= 90` is unauthorized drift and is blocked.
The checker compares APAC SOPs against the **APAC override** (effective policy),
not the global baseline, once an approved override exists.

> **MVP note:** this implementation uses the *lightweight* approach recommended
> in the design docs — the checker reads the regional override as the effective
> policy, and the calibration memo is documentation that justifies it. Wiring
> the checker to validate calibration-memo references directly is a documented
> future extension.

---

## Architecture

| File | Role |
|---|---|
| `main.py` | FastAPI backend — `/health`, `/upload-policy`, `/upload-sop`, `/upload-override`, `/validate` |
| `app.py` | Streamlit UI |
| `dataprep.py` | Ingest/extract text from uploads (PDF/DOCX/TXT/MD) or disk |
| `okr_extraction.py` | LLM extraction of structured control fields (OpenAI-compatible; OPEA-aligned) |
| `mock_extraction.py` | Deterministic offline extractor (used when `LLM_MODE=mock`) |
| `conformance_checker.py` | Threshold / role / time-window / step-omission drift detection |
| `remediation.py` | Jira + Confluence audit payload generation |
| `schemas.py` | Pydantic models |
| `run_demo.py` | Offline end-to-end runner + evaluation over all ground-truth cases |

Data lives under `data/` (policy hierarchy, SOP drafts, ground truth, sample
outputs). Regulatory grounding summaries are under `docs/grounding/`.

---

## Quick start

### Option A — zero-infrastructure demo (recommended first run)

No LLM, no Docker. Uses the deterministic mock extractor:

```bash
pip install -r requirements.txt
make demo            # or: LLM_MODE=mock python run_demo.py
make test            # run the unit tests
```

`make demo` runs all eight benchmark cases and prints a verdict-accuracy table,
writing `data/outputs/evaluation_metrics.json` and sample Jira/Confluence
payloads.

### Option B — full stack (backend + UI)

```bash
# terminal 1
make backend         # LLM_MODE=mock uvicorn main:app ... :8000
# terminal 2
make ui              # streamlit run app.py  (talks to :8000)
```

### Option C — Docker

```bash
docker compose up --build
# backend → http://localhost:8000  ·  UI → http://localhost:8501
```

### Using a real LLM

Unset `LLM_MODE` (or set it to anything other than `mock`) and point the
extractor at any OpenAI-compatible endpoint:

```bash
export LLM_ENDPOINT=http://localhost:9000/v1/chat/completions   # e.g. OPEA textgen
export LLM_MODEL=Intel/neural-chat-7b-v3-3
uvicorn main:app --port 8000
```

---

## Benchmark cases

Eight cases in `data/ground_truth/case_manifest.json`, each a realistic SOP under
a different business pressure:

| Case | Drift | Expected |
|---|---|---|
| CASE_001 | clean APAC SOP | PASS |
| CASE_002 | authorized override echo | PASS |
| CASE_003 | threshold 85→90 | BLOCK |
| CASE_004 | role swap (L2 → junior agent) | BLOCK |
| CASE_005 | time window 24h→72h | BLOCK |
| CASE_006 | step omission (gate moved post-approval) | BLOCK |
| CASE_007 | region mismatch (EU rules on APAC book) | BLOCK |
| CASE_008 | combo (threshold + role + time) | BLOCK |

Current verdict accuracy on these cases: **8/8**.

---

## Disclaimer

All policy, memo, and SOP documents in `data/` are **synthetic benchmark
artifacts** created to simulate an enterprise compliance approval process. They
are not real institutional documents and do not constitute regulatory advice.
