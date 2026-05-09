import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
POLICY_DIR = DATA_DIR / "policy_hierarchy"
SOP_DIR = DATA_DIR / "sop_drafts"


def load_text(filepath: Path) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def load_global_baseline() -> str:
    path = POLICY_DIR / "global_baseline_kyc_policy.md"
    return load_text(path)


def load_regional_override(region: str) -> str | None:
    region_map = {
        "APAC": "apac_override_policy.md",
        "EU": "eu_override_policy.md",
    }
    filename = region_map.get(region.upper())
    if not filename:
        return None
    path = POLICY_DIR / filename
    if not path.exists():
        return None
    return load_text(path)


def load_sop(filename: str) -> str:
    path = SOP_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"SOP file not found: {filename}")
    return load_text(path)


def list_sop_files() -> list[str]:
    return [f.name for f in SOP_DIR.glob("*.md")]
