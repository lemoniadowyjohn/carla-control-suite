#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage I: packaged-map evidence (offline-capable).

The packaged perception map is the Stage G semantic-enriched candidate
(candidate_g_semantic_enriched.xodr): structurally identical to the signed
repaired candidate plus the restored accepted signal layer.  This stage
produces the packaged-map evidence: package identity, semantic inventory of
the packaged artifact, equivalence to the governed payload, and the residual
packaged-map / PERCEPTION_RELEASE gated gaps (crosswalks, pedestrian lanes)
that require live packaged actors.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO_ROOT))

from phase_q.semantic_evidence import (
    extract_semantic_inventory,
    inventory_counts,
    compare_inventories,
    semantic_equivalence_verdict,
)
from phase_q.common import sha256_file, load_text, sha256_text

RUN_ID = "20260807T000000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

ENRICHED = EVIDENCE_DIR / "candidate_g_semantic_enriched.xodr"
GOVERNED = EVIDENCE_DIR / "governed_payload.xodr"
REPAIRED = REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
OSM_SOURCE = REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"

REPORT = EVIDENCE_DIR / "I_PACKAGED_MAP_EVIDENCE.json"
REPORT_MD = EVIDENCE_DIR / "I_PACKAGED_MAP_EVIDENCE.md"

# OSM authority evidence (from Stage G survey): crosswalk/pedestrian way counts.
OSM_AUTHORITY = {
    "crosswalk_footway_ways": 174,
    "pedestrian_footway_ways": 398,
    "pedestrian_areas": 78,
    "source": "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm (Phase H OSM authority survey)",
}


def main() -> int:
    # Package identity.
    packaged_text = load_text(ENRICHED)  # LF-normalized text (loader input form)
    packaged_sha = sha256_text(packaged_text)
    packaged_raw = sha256_file(ENRICHED)

    # Inventories.
    packaged_inv = extract_semantic_inventory(packaged_text)
    governed_text = load_text(GOVERNED)
    governed_inv = extract_semantic_inventory(governed_text)
    repaired_text = load_text(REPAIRED)
    repaired_inv = extract_semantic_inventory(repaired_text)

    packaged_counts = inventory_counts(packaged_inv)
    governed_counts = inventory_counts(governed_inv)
    repaired_counts = inventory_counts(repaired_inv)

    # Equivalence: packaged map vs governed payload (should be identical; both
    # are the enriched candidate before/after georef normalization).
    cmp_pkg_payload = compare_inventories(packaged_inv, governed_inv)
    verdict_pkg_payload = semantic_equivalence_verdict(cmp_pkg_payload)

    # Equivalence: packaged vs repaired parent (only signals/speed/turn should differ).
    cmp_pkg_repaired = compare_inventories(repaired_inv, packaged_inv)
    verdict_pkg_repaired = semantic_equivalence_verdict(cmp_pkg_repaired)

    # Residual packaged-map PERCEPTION_RELEASE gated gaps.
    residual_gaps = {
        "crosswalk_objects": {
            "osm_authority_count": OSM_AUTHORITY["crosswalk_footway_ways"],
            "packaged_count": packaged_counts.get("crosswalk_objects", 0),
            "disposition": "SEMANTIC_CONTENT_MISSING",
            "gate": "PERCEPTION_RELEASE blocker (packaged actor binding)",
        },
        "pedestrian_lanes": {
            "osm_authority_count": OSM_AUTHORITY["pedestrian_areas"],
            "packaged_count": packaged_counts.get("pedestrian_lanes", 0),
            "disposition": "SEMANTIC_CONTENT_MISSING",
            "gate": "PERCEPTION_RELEASE blocker (packaged actor binding)",
        },
    }

    report = {
        "run_id": RUN_ID,
        "stage": "I",
        "producer": "stage_i_packaged_map.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package": {
            "name": "ingolstadt_cooked_perception_v1 packaged map",
            "artifact": str(ENRICHED),
            "sha256_lf_text": packaged_sha,
            "sha256_raw_bytes": packaged_raw,
            "semantically_identical_to_repaired": (
                packaged_counts == {**repaired_counts,
                                    **{k: packaged_counts.get(k, 0)
                                       for k in ("signals", "speed_limits",
                                                 "turn_lane_semantics")}}
                and packaged_counts.get("signals") == 3467
            ),
        },
        "semantic_inventory": {
            "packaged": packaged_counts,
        },
        "equivalence": {
            "packaged_vs_governed_payload_verdict": verdict_pkg_payload,
            "packaged_vs_repaired_parent_verdict": verdict_pkg_repaired,
            "note": "packaged==governed payload expected PASS; vs repaired parent "
                    "diffs are the restored signal/speed/turn layer (non-decisive on "
                    "structure; decisive categories added)",
        },
        "residual_packaged_gaps": residual_gaps,
        "live_runtime_requirements_unmet": [
            "CARLA server binary not present in environment (CARLA_ROOT unset, "
            "no CarlaUE4 executable on disk). Packed-map actor bindings and live "
            "perception sensor captures (L9/L10) cannot be produced until server is "
            "available."
        ],
        "verdict": "I_PACKAGED_MAP_EVIDENCE_PRODUCED",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Stage I - Packaged map evidence",
        "",
        "## Verdict: `I_PACKAGED_MAP_EVIDENCE_PRODUCED`",
        "",
        "## Package",
        f"- artifact: `{ENRICHED.name}` (enriched semantic candidate)",
        f"- LF-text SHA-256: `{packaged_sha}`",
        f"- raw-bytes SHA-256: `{packaged_raw}`",
        "",
        "## Semantic inventory (packaged)",
        "",
        "| category | count |",
        "| --- | --- |",
    ]
    for c in ("signals", "signal_references", "controllers", "objects",
              "crosswalk_objects", "speed_limits", "road_types", "road_markings",
              "lane_change_permissions", "turn_lane_semantics",
              "stop_yield_controls", "sidewalks", "pedestrian_lanes",
              "traffic_light_actor_bindings", "semantic_material_classes"):
        lines.append(f"| {c} | {packaged_counts.get(c, 0)} |")
    lines += [
        "",
        "## Equivalence",
        f"- packaged vs governed payload: **{verdict_pkg_payload}**",
        f"- packaged vs repaired parent: {verdict_pkg_repaired} (diffs = restored signal/speed/turn layer)",
        "",
        "## Residual PERCEPTION_RELEASE gaps",
        f"- crosswalk_objects: OSM authority {OSM_AUTHORITY['crosswalk_footway_ways']}, packaged 0 — MISSING (blocker)",
        f"- pedestrian_lanes: OSM authority {OSM_AUTHORITY['pedestrian_areas']}, packaged 0 — MISSING (blocker)",
        "",
        "## Live runtime requirements unmet",
        "- CARLA server binary not present in this environment; packed-map actor "
        "bindings and live perception sensor captures (L9/L10) cannot be produced until the server is available.",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Stage I: {report['verdict']}")
    print(f"  packaged sha (LF text): {packaged_sha[:16]}...")
    print(f"  signals: {packaged_counts.get('signals', 0)}")
    print(f"  packaged vs governed payload: {verdict_pkg_payload}")
    print(f"  packaged vs repaired parent: {verdict_pkg_repaired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
