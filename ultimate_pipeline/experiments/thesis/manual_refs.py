from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Any


MANUAL_INGOLSTADT_REFS: Dict[str, Dict[str, Any]] = {
    "Grid0821": {
        "manual_xodr_path": "manual_maps/Grid0821.xodr",
        "manual_xodr_fallbacks": [
            "_pair_capture_manual/Grid0821_20260125_204453/xodr_hardened.xodr",
            "_pair_capture_manual/Grid0821_20260125_204339/xodr_hardened.xodr",
        ],
        "cooked_town": "Grid0821",
    },
    "Grid0828": {
        "manual_xodr_path": "manual_maps/manual_ingolstadt_grid0828.xodr",
        "manual_xodr_fallbacks": [
            "_perception_runs/manual_town_Grid0828_20260125_205531/xodr_hardened.xodr",
            "artifacts/final_runs/scenario_b_audit/evidence/strict_evidence/_normalized_input.xodr",
        ],
        "cooked_town": "Grid0828",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_manual_town(manual_town: str) -> Dict[str, Any]:
    key = str(manual_town or "").strip()
    if key not in MANUAL_INGOLSTADT_REFS:
        raise ValueError(f"Unknown manual_town: {manual_town}. Expected one of {sorted(MANUAL_INGOLSTADT_REFS.keys())}")
    entry = MANUAL_INGOLSTADT_REFS[key]
    
    # Try primary
    manual_xodr = (_repo_root() / entry["manual_xodr_path"]).resolve()
    
    # Try fallbacks if primary missing
    if not manual_xodr.is_file():
        for fallback in entry.get("manual_xodr_fallbacks", []):
            cand = (_repo_root() / fallback).resolve()
            if cand.is_file():
                manual_xodr = cand
                break
                
    if not manual_xodr.is_file():
        raise FileNotFoundError(
            f"Manual XODR not found for {key}. Searched primary '{entry['manual_xodr_path']}' "
            f"and {len(entry.get('manual_xodr_fallbacks', []))} fallbacks."
        )
        
    return {
        "manual_town": key,
        "manual_xodr_path": str(manual_xodr),
        "cooked_town": entry["cooked_town"],
    }


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def assert_manual_auto_distinct(manual_xodr: Path, auto_xodr: Path) -> Dict[str, str]:
    manual_hash = sha256_file(manual_xodr)
    auto_hash = sha256_file(auto_xodr)
    if manual_hash and auto_hash and manual_hash == auto_hash:
        raise RuntimeError("Manual and auto XODR are identical; check inputs.")
    return {"manual_xodr_sha256": manual_hash, "auto_xodr_sha256": auto_hash}
