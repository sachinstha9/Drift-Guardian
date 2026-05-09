import json
import httpx
from typing import List
from schemas import OKRField

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b"

EXTRACTION_PROMPT = """You are a compliance document analyst. Extract structured control fields from the following KYC document text.

For each compliance control you find, extract these fields:
- control_id: a short identifier like KYC_HIGH_RISK_REVIEW
- trigger: what event triggers this control
- threshold: any numeric or conditional threshold (e.g. risk_score >= 80)
- required_actor: the role/person responsible (e.g. L2 Compliance Analyst)
- required_action: what action must be taken
- time_window: time limit for the action (e.g. within 24 hours)
- region: geographic region this applies to
- evidence_span: the exact sentence(s) from the text that describe this control

Return ONLY a valid JSON array of objects with these fields. No explanation, no markdown, just JSON.

Document text:
{text}
"""


async def extract_okr_fields(text: str, filename: str = "") -> List[OKRField]:
    prompt = EXTRACTION_PROMPT.format(text=text)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1}
            })
            response.raise_for_status()
            raw = response.json().get("response", "")

            # clean up response - strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            data = json.loads(raw)
            fields = []
            for item in data:
                if not item.get("evidence_span"):
                    continue  # drop claims with no evidence
                fields.append(OKRField(**{k: v for k, v in item.items()
                                          if k in OKRField.model_fields}))
            return fields

    except Exception as e:
        print(f"[OKR extraction error] {e}")
        return []
