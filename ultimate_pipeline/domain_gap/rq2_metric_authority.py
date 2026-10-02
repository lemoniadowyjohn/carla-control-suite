#!/usr/bin/env python3
"""RQ2 metric authority — production RQ2 entrypoint.

Resolves the pinned auto/manual pair via the C13 registry (never by mtime or
glob), computes the thesis-contract RQ2 metrics under an explicit scope, and
emits machine-readable results + provenance.

Scopes (never mixed):
  manual_hull: crop auto road network to the manual map's convex-hull
    footprint, then compare. This is the PRIMARY RQ2 scope — it measures the
    structural domain gap for the same region.
  whole_map: compare full auto extraction vs the manual patch with no
    cropping. Context only — dominated by the scope artifact (full OSM
    extraction ~13x14 km vs curated ~4.4x2.9 km patch). Construction layers
    (traffic lights, buildings-as-modeled) are reported here, not in hull.

Valid RQ2 metrics (research/thesis_rq_contract.yaml, RQ2.valid_metrics):
  lane_width_gap, curvature_gap, curvature_wasserstein_gap, road_count_ratio,
  road_length_ratio, junction_ratio, building_density_gap, frechet_distance,
  connectivity_gap, semantic_object_gap
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

WORKTREE = Path(__file__).resolve().parents[2]
if str(WORKTREE) not in sys.path:
    sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

VALID_METRICS = [
    "lane_width_gap",
    "curvature_gap",
    "curvature_wasserstein_gap",
    "road_count_ratio",
    "road_length_ratio",
    "junction_ratio",
    "building_density_gap",
    "frechet_distance",
    "connectivity_gap",
    "semantic_object_gap",
]

SCOPES = ("manual_hull", "whole_map")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def resolve_pair() -> Dict[str, Any]:
    auto = verify_pinned_map("auto_map_of_record")
    manual = verify_pinned_map("manual_grid0828")
    assert auto.get("verification_status") == "VERIFIED", auto
    assert manual.get("verification_status") == "VERIFIED", manual
    return {"auto": auto, "manual": manual}


def compute_manual_hull(auto_path: str, manual_path: str) -> Dict[str, Any]:
    from ultimate_pipeline.domain_gap.local_registration import (
        compute_local_registration,
        local_structural_summary,
    )
    from ultimate_pipeline.domain_gap.frechet_gap import compute_frechet_gap

    reg = compute_local_registration(auto_path, manual_path, footprint="hull")
    summary = local_structural_summary(reg)
    frechet = compute_frechet_gap(auto_path, manual_path, footprint="hull")
    m, ca = reg.manual_stats, reg.cropped_auto_stats
    return {
        "scope": "manual_hull",
        "footprint": "hull",
        "metrics": {
            "lane_width_gap": summary["road_network_structural"]["lane_width_gap"],
            "curvature_gap": summary["road_network_structural"]["curvature_gap"],
            "curvature_wasserstein_gap": summary["road_network_structural"]["curvature_wasserstein_gap"],
            "road_count_ratio": summary["road_network_structural"]["road_count_ratio_auto_over_manual"],
            "road_length_ratio": summary["road_network_structural"]["road_length_ratio_auto_over_manual"],
            "junction_ratio": summary["road_network_structural"]["junction_ratio_auto_over_manual"],
            "building_density_gap": summary["building_density_comparison"]["building_density_gap"],
            "frechet_distance": {
                "mean_m": frechet.get("mean_m"),
                "median_m": frechet.get("median_m"),
                "p90_m": frechet.get("p90_m"),
                "pairs": frechet.get("matched_pair_count"),
            },
        },
        "support": {
            "manual_roads": m.num_roads,
            "cropped_auto_roads": ca.num_roads,
            "full_auto_roads": reg.full_auto_road_count,
            "manual_length_m": round(m.total_road_length, 1),
            "cropped_auto_length_m": round(ca.total_road_length, 1),
            "manual_junctions": m.num_junctions,
            "cropped_auto_junctions": ca.num_junctions,
        },
        "implementations": {
            "ratios_gaps": "ultimate_pipeline.domain_gap.local_registration.compute_local_registration+local_structural_summary (footprint=hull)",
            "frechet_distance": "ultimate_pipeline.domain_gap.frechet_gap.compute_frechet_gap (footprint=hull, spacing_m=5.0)",
        },
    }


def compute_whole_map(auto_path: str, manual_path: str) -> Dict[str, Any]:
    from pathlib import Path as _P
    from ultimate_pipeline.tools.xodr_structural_summary import summarize_xodr
    from ultimate_pipeline.domain_gap.connectivity_gap import ConnectivityGap
    from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap

    a = summarize_xodr(_P(auto_path))
    m = summarize_xodr(_P(manual_path))
    conn = ConnectivityGap.compute(manual_path, auto_path)
    sem = SemanticGap.compute(manual_path, auto_path)
    return {
        "scope": "whole_map",
        "footprint": "none (full files, context only)",
        "metrics": {
            "road_count_ratio": round(a["road_count"] / m["road_count"], 3) if m["road_count"] else None,
            "road_length_ratio": round(a["total_road_length_m"] / m["total_road_length_m"], 3) if m["total_road_length_m"] else None,
            "junction_ratio": round(a["junction_count"] / m["junction_count"], 3) if m["junction_count"] else None,
            "building_density_gap": None,
            "connectivity_gap": conn,
            "semantic_object_gap": sem,
        },
        "support": {
            "auto_roads": a["road_count"],
            "manual_roads": m["road_count"],
            "auto_length_m": round(a["total_road_length_m"], 1),
            "manual_length_m": round(m["total_road_length_m"], 1),
            "auto_junctions": a["junction_count"],
            "manual_junctions": m["junction_count"],
        },
        "implementations": {
            "ratios": "ultimate_pipeline.tools.xodr_structural_summary.summarize_xodr (full files)",
            "connectivity_gap": "ultimate_pipeline.domain_gap.connectivity_gap.ConnectivityGap.compute",
            "semantic_object_gap": "ultimate_pipeline.domain_gap.semantic_gap.SemanticGap.compute",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", choices=list(SCOPES) + ["both"], default="both")
    ap.add_argument("--out", type=Path, default=Path("RQ2_RESULTS.json"))
    ap.add_argument("--provenance-out", type=Path, default=Path("RQ2_METRIC_PROVENANCE.json"))
    args = ap.parse_args()

    pair = resolve_pair()
    auto_p = pair["auto"]["resolved_path"]
    manual_p = pair["manual"]["resolved_path"]
    out: Dict[str, Any] = {
        "schema": "rq2_results/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pair": {
            "auto": {"path": pair["auto"]["declared_path"], "sha256": pair["auto"]["sha256_actual"], "bytes": pair["auto"]["bytes_actual"]},
            "manual": {"path": pair["manual"]["declared_path"], "sha256": pair["manual"]["sha256_actual"], "bytes": pair["manual"]["bytes_actual"]},
        },
        "valid_metrics": VALID_METRICS,
        "scopes": {},
    }
    if args.scope in ("manual_hull", "both"):
        out["scopes"]["manual_hull"] = compute_manual_hull(auto_p, manual_p)
    if args.scope in ("whole_map", "both"):
        out["scopes"]["whole_map"] = compute_whole_map(auto_p, manual_p)

    args.out.write_text(json.dumps(out, indent=2, sort_keys=True, default=str) + "\n")
    prov = {
        "schema": "rq2_metric_provenance/v1",
        "generated_at_utc": out["generated_at_utc"],
        "pair_sha256": {"auto": out["pair"]["auto"]["sha256"], "manual": out["pair"]["manual"]["sha256"]},
        "metric_implementation": {
            "manual_hull": (out["scopes"].get("manual_hull", {}).get("implementations", {})),
            "whole_map": (out["scopes"].get("whole_map", {}).get("implementations", {})),
        },
        "scope_policy": "manual_hull and whole_map metrics are computed independently and never averaged or mixed.",
        "contract": "research/thesis_rq_contract.yaml RQ2.valid_metrics",
    }
    args.provenance_out.write_text(json.dumps(prov, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"scopes": list(out["scopes"].keys()), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
