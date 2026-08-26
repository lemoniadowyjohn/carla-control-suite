#!/usr/bin/env python3
"""Regenerate reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json.

Runs ultimate_pipeline.domain_gap.local_registration.compute_local_registration on the
pinned Ingolstadt auto/manual pair, for BOTH footprint kinds ("hull" = default/tighter,
"bbox" = legacy/wider), and writes a JSON with both sets of numbers side by side so the
delta between them is never silently lost.

Usage:
    UP_DISABLE_CARLA=1 python scripts/regen_local_registration.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(__file__, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ultimate_pipeline.domain_gap.local_registration import (  # noqa: E402
    compute_local_registration,
    local_structural_summary,
)

AUTO_XODR = "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr"
MANUAL_XODR = "campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr"
OUT_PATH = "reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _crop_block(result) -> dict:
    m, ca = result.manual_stats, result.cropped_auto_stats
    return {
        "full_auto_road_count": result.full_auto_road_count,
        "cropped_auto_road_count": result.cropped_auto_road_count,
        "manual_road_count": m.num_roads,
        "cropped_auto_total_length_m": round(ca.total_road_length, 1),
        "manual_total_length_m": round(m.total_road_length, 1),
        "cropped_auto_junctions": ca.num_junctions,
        "manual_junctions": m.num_junctions,
        "full_auto_building_count": result.provenance["full_auto_building_count"],
        "cropped_auto_buildings": ca.num_buildings,
        "manual_buildings": m.num_buildings,
        "cropped_auto_traffic_lights": ca.num_traffic_lights,
        "footprint_local_bounds": list(result.footprint_local_bounds),
    }


def _gap_block(gap) -> dict:
    return {
        "lane_width_gap": round(gap.lane_width_gap, 4),
        "curvature_gap": round(gap.curvature_gap, 4),
        "road_length_gap": round(gap.road_length_gap, 4),
        "traffic_light_density_gap": round(gap.traffic_light_density_gap, 4),
        "building_density_gap": round(gap.building_density_gap, 4),
        "road_type_coverage_gap": round(gap.road_type_coverage_gap, 4),
    }


def main() -> None:
    hull_result = compute_local_registration(AUTO_XODR, MANUAL_XODR, footprint="hull")
    bbox_result = compute_local_registration(AUTO_XODR, MANUAL_XODR, footprint="bbox")

    whole_map_gap = {
        # Pinned whole-map gap from C14 (unaffected by this crop-method change); carried
        # forward verbatim for the side-by-side comparison table.
        "lane_width_gap": 0.0415,
        "curvature_gap": 0.0931,
        "road_length_gap": 1.0,
        "traffic_light_density_gap": 1.0,
        "building_density_gap": 0.7951,
        "road_type_coverage_gap": 0.0,
    }

    out = {
        "note": (
            "LOCAL structural gap: auto map cropped to Grid0828's geographic footprint "
            "(removes scope artifact). DEFAULT footprint is now the convex HULL of "
            "Grid0828's planView geometry (tighter than the legacy bounding box -- hull "
            "area <= bbox area always). Both footprint kinds are reported here "
            "side-by-side per the C26 claim-boundary requirement: the hull crop "
            "materially lowers the road-network ratios vs. the bbox crop (see "
            "road_network_structural in each block below), so both are kept explicit "
            "rather than silently overwriting the prior bbox-only result."
        ),
        "footprint_default": "hull",
        "hull": {
            "local_structural_summary": local_structural_summary(hull_result),
            "local_gap_raw": _gap_block(hull_result.local_gap),
            "crop": _crop_block(hull_result),
            "provenance": {**hull_result.provenance, "auto_offset": list(hull_result.provenance["auto_offset"]),
                           "building_frame_shift": list(hull_result.provenance["building_frame_shift"])},
        },
        "bbox": {
            "local_structural_summary": local_structural_summary(bbox_result),
            "local_gap_raw": _gap_block(bbox_result.local_gap),
            "crop": _crop_block(bbox_result),
            "provenance": {**bbox_result.provenance, "auto_offset": list(bbox_result.provenance["auto_offset"]),
                           "building_frame_shift": list(bbox_result.provenance["building_frame_shift"])},
        },
        "whole_map_gap": whole_map_gap,
        "source_files": {
            "auto_xodr": AUTO_XODR,
            "auto_xodr_sha256": _sha256(AUTO_XODR),
            "manual_xodr": MANUAL_XODR,
            "manual_xodr_sha256": _sha256(MANUAL_XODR),
        },
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"wrote {OUT_PATH}")
    print(f"hull:  roads {hull_result.cropped_auto_road_count}/{hull_result.full_auto_road_count}, "
          f"buildings {hull_result.provenance['cropped_auto_building_count']}/{hull_result.provenance['full_auto_building_count']}")
    print(f"bbox:  roads {bbox_result.cropped_auto_road_count}/{bbox_result.full_auto_road_count}, "
          f"buildings {bbox_result.provenance['cropped_auto_building_count']}/{bbox_result.provenance['full_auto_building_count']}")


if __name__ == "__main__":
    main()
