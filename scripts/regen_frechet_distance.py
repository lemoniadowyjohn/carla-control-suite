#!/usr/bin/env python3
"""Regenerate reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/frechet_distance.json.

Runs ultimate_pipeline.domain_gap.frechet_gap.compute_frechet_gap on the pinned Ingolstadt
auto/manual pair (default "hull" footprint, matching THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md's
original methodology and scripts/regen_local_registration.py's default), and writes a JSON with
the result plus source-file provenance (paths + sha256) so the report can never again go stale
without an obvious re-run trail.

This is the sibling of scripts/regen_local_registration.py, fixed the same way on 2026-09-17:
THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md's mean 55.28m / median 35.26m / p90 128.01m / 895
pairs figures were computed once, as a one-off invocation, against the map-of-record pin that was
current on 2026-08-27 (`744757f3...`) -- 6+ promotions stale as of 2026-09-17 (current pin
`370abbbbb3...`). No script for that computation survived in git history. This script resolves the
auto-side XODR through the C13 pin registry instead of a hardcoded path, so this specific
staleness cannot recur silently on future promotions.

Usage:
    UP_DISABLE_CARLA=1 python scripts/regen_frechet_distance.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(__file__, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ultimate_pipeline.domain_gap.frechet_gap import compute_frechet_gap  # noqa: E402
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map  # noqa: E402

AUTO_XODR = verify_pinned_map("auto_map_of_record")["path"]
MANUAL_XODR = "campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr"
OUT_PATH = "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/frechet_distance.json"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_output(auto_xodr: str, manual_xodr: str, *, footprint: str = "hull") -> dict:
    """Compute the Frechet-distance result and wrap it with source-file provenance.

    Split out from main() so tests can exercise it directly against small synthetic XODR
    fixtures without touching the real pin registry (mirrors the compute_frechet_gap tests in
    tests/unit/test_frechet_gap.py, which already cover the underlying math/matching/resampling
    -- this function is only the thin "resolve + wrap + persist" layer around it).
    """
    result = compute_frechet_gap(auto_xodr, manual_xodr, footprint=footprint)
    return {
        "note": (
            "Discrete Frechet distance (thesis future-work item #14), per matched manual<->auto "
            "road pair, after cropping auto to the manual map's convex-hull footprint and "
            "reprojecting both centerlines into manual's own CRS -- the current, correct RQ1/RQ2 "
            "local-registration methodology (see THESIS_ITEM14_FRECHET_DISTANCE_RECOMPUTED.md), "
            "not the thesis's original uncropped whole-network SE(2)-aligned comparison."
        ),
        "result": result,
        "source_files": {
            "auto_xodr": auto_xodr,
            "auto_xodr_sha256": _sha256(auto_xodr),
            "manual_xodr": manual_xodr,
            "manual_xodr_sha256": _sha256(manual_xodr),
        },
    }


def main() -> None:
    out = build_output(AUTO_XODR, MANUAL_XODR, footprint="hull")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    r = out["result"]
    print(f"wrote {OUT_PATH}")
    print(
        f"matched_pair_count={r['matched_pair_count']} mean_m={r['mean_m']} "
        f"median_m={r['median_m']} p90_m={r['p90_m']}"
    )


if __name__ == "__main__":
    main()
