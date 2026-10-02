#!/usr/bin/env python3
"""Batch-10 RQ2 lane driver: regenerate candidate RQ2 evidence (lane-local only).

Resolves the auto map through the pin registry, runs the RQ2 metric authority
for manual_hull (primary) and whole_map (supplementary context), and writes
lane-local outputs. NEVER writes canonical post_audit_hardening evidence.
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(__file__, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.domain_gap.rq2_metric_authority import run_rq2_comparison

RUN_ID = os.environ.get("RQ2_RUN_ID", "20261002_batch10")
OUT_DIR = os.path.join(ROOT, "reports", "parallel_wave", "rq2", RUN_ID)

EXPECTED_AUTO_SHA256 = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
MANUAL_REL = os.path.join(
    "campaigns", "ingolstadt_cooked_perception_v1", "source", "manual", "Grid0828.xodr"
)


def main() -> int:
    t0 = time.time()
    reg = verify_pinned_map("auto_map_of_record")
    if reg.get("verification_status") != "VERIFIED":
        print(f"FAIL: MAP_AUTHORITY_DRIFT: {reg}")
        return 1
    if reg.get("sha256_actual") != EXPECTED_AUTO_SHA256:
        print(
            "FAIL: MAP_AUTHORITY_DRIFT: registry SHA "
            f"{reg.get('sha256_actual')} != expected {EXPECTED_AUTO_SHA256}"
        )
        return 1
    auto_xodr = reg["resolved_path"]
    manual_xodr = os.path.join(ROOT, MANUAL_REL)
    os.makedirs(OUT_DIR, exist_ok=True)

    base_cfg = {
        "verify_shas": True,
        "expected_auto_sha256": EXPECTED_AUTO_SHA256,
    }

    print("[rq2] running manual_hull (primary)...", flush=True)
    hull = run_rq2_comparison(auto_xodr, manual_xodr, "manual_hull", dict(base_cfg))
    print("[rq2] manual_hull done.", flush=True)

    print("[rq2] running whole_map (supplementary)...", flush=True)
    whole = run_rq2_comparison(auto_xodr, manual_xodr, "whole_map", dict(base_cfg))
    print("[rq2] whole_map done.", flush=True)

    results = {
        "run_id": RUN_ID,
        "manual_hull": hull.to_dict(),
        "whole_map": whole.to_dict(),
    }
    with open(os.path.join(OUT_DIR, "RQ2_RESULTS.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    provenance = {
        "run_id": RUN_ID,
        "registry": reg,
        "manual_hull_provenance": hull.provenance,
        "whole_map_provenance": whole.provenance,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(OUT_DIR, "RQ2_METRIC_PROVENANCE.json"), "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)

    hp, wp = hull.primary, whole.primary
    lines = [
        "# RQ2 candidate results (batch10 lane-local, NOT canonical)",
        "",
        f"run_id: {RUN_ID}",
        f"auto_sha256: {hull.provenance['auto_sha256']}",
        f"manual_sha256: {hull.provenance['manual_sha256']}",
        f"candidate_commit: {hull.provenance['candidate_commit']}",
        "",
        "## manual_hull (PRIMARY)",
        "",
        f"lane_width_gap: {hp['lane_width_gap']}",
        f"curvature_gap: {hp['curvature_gap']}",
        f"curvature_wasserstein_gap: {hp['curvature_wasserstein_gap']}",
        f"road_length_ratio: {hp['road_length_ratio']}",
        f"junction_ratio: {hp['junction_ratio']}",
        f"road_count_ratio: {hp['road_count_ratio']}",
        f"building_density_gap: {hp['building_density_gap']}",
        f"frechet_distance: mean={hp['frechet_distance'].get('mean_m')} "
        f"median={hp['frechet_distance'].get('median_m')} "
        f"p90={hp['frechet_distance'].get('p90_m')} "
        f"pairs={hp['frechet_distance'].get('matched_pair_count')}",
        "",
        "## whole_map (SUPPLEMENTARY context)",
        "",
        f"lane_width_gap: {wp['lane_width_gap']}",
        f"curvature_gap: {wp['curvature_gap']}",
        f"curvature_wasserstein_gap: {wp['curvature_wasserstein_gap']}",
        f"road_length_ratio: {wp['road_length_ratio']}",
        f"junction_ratio: {wp['junction_ratio']}",
        f"road_count_ratio: {wp['road_count_ratio']}",
        f"building_density_gap: {wp['building_density_gap']}",
        f"frechet_distance: {wp['frechet_distance'].get('status')}",
        "",
    ]
    with open(os.path.join(OUT_DIR, "RQ2_RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[rq2] wrote {OUT_DIR} in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
