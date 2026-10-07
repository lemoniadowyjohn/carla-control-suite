"""Run-scoped ImportSettings isolation.

The shared ``importsetting.json`` (written to CWD by Import.py) is a proven
concurrency hazard: run B overwrites run A's settings mid-flight. Every
governed run must instead use ``<run_root>/<run_id>/importsetting.json``,
immutable for the life of the operation, SHA256-recorded, absolute path
bound into the command receipt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_run_settings(run_root: Path, run_id: str,
                        groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write an immutable, content-addressed importsetting.json for one run."""
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)  # fail if run_id reused
    payload = {"ImportGroups": groups}
    text = json.dumps(payload, indent=2, sort_keys=True)
    path = run_dir / "importsetting.json"
    path.write_text(text, encoding="utf-8")
    try:
        import os

        os.chmod(path, 0o444)  # read-only: immutable for run lifetime
    except OSError:
        pass
    return {"path": str(path), "sha256": _sha256_text(text),
            "run_id": run_id}


def semantic_sha(groups: List[Dict[str, Any]]) -> str:
    """Fingerprint of the semantic content (paths normalized to posix)."""
    norm = json.loads(json.dumps(groups, sort_keys=True).replace("\\", "/"))
    return _sha256_text(json.dumps(norm, sort_keys=True,
                                   separators=(",", ":")))


def verify_immutable(record: Dict[str, Any]) -> Dict[str, Any]:
    """Re-check that a run's settings file is unchanged since creation."""
    p = Path(record["path"])
    try:
        current = _sha256_text(p.read_text(encoding="utf-8"))
    except OSError as e:
        return {"ok": False, "reason": f"unreadable: {e}"}
    if current != record["sha256"]:
        return {"ok": False, "reason": "MUTATED_DURING_RUN",
                "expected": record["sha256"], "actual": current}
    return {"ok": True}


def reject_duplicate_fingerprint(candidate_fp: str,
                                 live_fingerprints: List[str]) -> Optional[str]:
    if candidate_fp in live_fingerprints:
        return "DUPLICATE_OPERATION_ALREADY_RUNNING"
    return None
