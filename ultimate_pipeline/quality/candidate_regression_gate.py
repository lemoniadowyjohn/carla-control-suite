"""General-purpose candidate-vs-baseline regression gate.

Extracted from ultimate_pipeline/tools/phase_g8_acceptance.py, which contains
two genuinely reusable ideas not duplicated anywhere else in the live
pipeline (confirmed by direct inspection of map_acceptance.py, the official
acceptance gate: it has no equivalent check):

1. Protected-domain identity-hash regression: has any of the 7 protected
   geometric/topological domains (planview, road length, elevation profile,
   road links, junction structure, connector geometry, contactPoints)
   silently drifted between a candidate and the map it's meant to replace?
2. Loadability error-signature regression: did the candidate introduce a NEW
   CARLA-loadability error class, or exceed a prior error count for an
   existing class, versus the baseline?

phase_g8_acceptance.py itself is a frozen historical record of the original
Phase-G construction freeze (hardcoded RUN_ID and two specific August 2026
evidence-file paths) and is NOT modified by this module -- this is a new,
general-purpose implementation any two XODR files can be passed to.

This session has repeatedly asked for an ad-hoc "MAP_OF_RECORD_ACCEPTANCE_
DELTA" in nearly every prompt; this module is the reusable version of that.
"""
from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

from ultimate_pipeline.tools.phase_g0_handoff import compute_identity_hashes
from ultimate_pipeline.tools.preflight_xodr_loadability import run_preflight

PROTECTED_KEYS = [
    "planview_hash",
    "road_length_hash",
    "elevation_profile_hash",
    "road_link_hash",
    "junction_structure_hash",
    "connector_geometry_hash",
    "contactpoint_hash",
]


def _error_signature(load: Dict[str, Any]) -> Dict[str, int]:
    return dict(Counter(
        f"{e.get('module')}|{e.get('code')}" for e in load.get("errors", [])
    ))


def compare_candidate_to_baseline(
    baseline_xodr_path: str,
    candidate_xodr_path: str,
    *,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare `candidate_xodr_path` against `baseline_xodr_path` for
    protected-domain identity drift and loadability regressions.

    Neither file is read as anything but a plain XODR path -- no hardcoded
    paths, no assumption about which is "newer". Returns a dict with a
    top-level "verdict": "REGRESSION_CLEAN" | "REGRESSION_DETECTED", plus
    the specific domain(s)/error-class(es) that changed when detected.
    """
    work_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="candidate_regression_gate_"))
    work_dir.mkdir(parents=True, exist_ok=True)

    baseline_identity = compute_identity_hashes(Path(baseline_xodr_path))
    candidate_identity = compute_identity_hashes(Path(candidate_xodr_path))
    protected_checks = {
        key: baseline_identity.get(key) == candidate_identity.get(key)
        for key in PROTECTED_KEYS
    }
    protected_ok = all(protected_checks.values())

    baseline_load = run_preflight(Path(baseline_xodr_path), work_dir / "baseline_preflight")
    candidate_load = run_preflight(Path(candidate_xodr_path), work_dir / "candidate_preflight")
    sig_baseline = _error_signature(baseline_load)
    sig_candidate = _error_signature(candidate_load)
    new_or_exceeded_errors: Dict[str, Dict[str, int]] = {}
    for key, count in sig_candidate.items():
        baseline_count = sig_baseline.get(key, 0)
        if count > baseline_count:
            new_or_exceeded_errors[key] = {"candidate": count, "baseline": baseline_count}
    loadability_ok = not new_or_exceeded_errors

    verdict = "REGRESSION_CLEAN" if (protected_ok and loadability_ok) else "REGRESSION_DETECTED"

    return {
        "baseline_xodr": str(baseline_xodr_path),
        "candidate_xodr": str(candidate_xodr_path),
        "verdict": verdict,
        "identity": {
            "protected_hash_matches": protected_checks,
            "protected_ok": protected_ok,
            "baseline_road_count": baseline_identity.get("road_count"),
            "candidate_road_count": candidate_identity.get("road_count"),
            "baseline_lane_topology_hash": baseline_identity.get("lane_topology_hash"),
            "candidate_lane_topology_hash": candidate_identity.get("lane_topology_hash"),
        },
        "loadability": {
            "baseline_status": baseline_load.get("summary", {}).get("status"),
            "candidate_status": candidate_load.get("summary", {}).get("status"),
            "baseline_error_signature": sig_baseline,
            "candidate_error_signature": sig_candidate,
            "new_or_exceeded_error_classes": new_or_exceeded_errors,
            "loadability_ok": loadability_ok,
        },
        "work_dir": str(work_dir),
    }
