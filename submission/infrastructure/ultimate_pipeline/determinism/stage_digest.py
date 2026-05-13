"""Determinism guard that fingerprints thesis stage directories for provenance logging.

Determinism hygiene note:
- The generated_at_utc field is intentionally EXCLUDED from determinism comparisons
  because it captures wall-clock time, not pipeline state.
- When comparing stage_hashes.json files across runs, ignore generated_at_utc.
- The stage_digest_sha256 field is computed from file contents only, not timestamps.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

SOURCE_FILES = [
    "run_metadata.json",
    "structural_summary.json",
    "full_report.json",
    "osm_to_xodr_manifest.json",
    "determinism_summary.json",
    "osm_to_xodr_determinism.json",
    "carla_status.json",
    "perception_gap.json",
]


def _read_bytes(path: Path) -> bytes:
    with path.open("rb") as fh:
        return fh.read()


def _safe_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_lines(files: List[Dict[str, Any]]) -> str:
    if not files:
        return _safe_sha256(b"")
    lines = "\n".join(f"{entry['sha256']}  {entry['relpath']}" for entry in files)
    return _safe_sha256((lines + "\n").encode("utf-8"))


def generate_stage_hashes(stage_dir: Path) -> Dict[str, Any]:
    """Collect deterministic hashes over well-known stage artifacts."""
    stage_path = Path(stage_dir)
    stage_path.mkdir(parents=True, exist_ok=True)
    files: List[Dict[str, Any]] = []
    for rel in sorted(SOURCE_FILES):
        candidate = stage_path / rel
        if not candidate.is_file():
            continue
        data = _read_bytes(candidate)
        files.append(
            {
                "relpath": rel,
                "sha256": _safe_sha256(data),
                "bytes": len(data),
            }
        )
    digest = _digest_lines(files)
    payload = {
        "stage_dir": str(stage_path.resolve()),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "files": files,
        "stage_digest_sha256": digest,
    }
    (stage_path / "stage_hashes.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return payload
