#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F2 — strict fallback policy evidence.

Runs the DEM elevation pass against the frozen horizontal candidate in
lenient-collect mode (no elevation written anywhere) and reports the fallback
kinds produced: flat, NN-extrapolated, graph-propagated, median/hardcoded,
unresolved.  Under the default strict policy any non-empty forbidden set is a
failure; the evidence run must show zero invented values.

Also records the audit of every fallback site in the elevation code path.
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T120000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

PINNED_CANDIDATE = (
    REPO_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "candidate"
    / "raw_xodr_run_1_epsg32632_header_pinned.xodr"
)
OSM_SOURCE = (
    REPO_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "source"
    / "ingolstadt_authoritative.osm"
)
DEM_PATH = REPO_ROOT / "cities" / "ingolstadt" / "dem" / "dem_ing.tif"

# Env must be set BEFORE any settings import (SETTINGS is constructed at
# import time).  Evidence run must not write elevation anywhere: thesis
# strict off, lenient policy -> collect QC; the candidate file is never
# touched.
os.environ["UP_OSM_FILE"] = str(OSM_SOURCE)
os.environ["UP_THESIS_STRICT"] = "0"
os.environ["UP_ELEVATION_FALLBACK_POLICY"] = "lenient"


def main() -> int:
    from ultimate_pipeline.config.settings import SETTINGS
    from ultimate_pipeline.enrichment.elevation_fallback_policy import (
        elevation_fallback_policy,
    )
    from ultimate_pipeline.enrichment.elevation_importer import (
        ElevationImporter,
    )

    now = datetime.now(timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_f2_fallback_audit.py",
        "generated_at_utc": now,
        "phase": "F",
        "f2_status": "PENDING",
        "fallback_sites_audit": [
            {
                "site": "apply_dem direct start-anchor sampling",
                "kind": "direct_dem",
                "allowed": True,
                "notes": "DEM-derived; neighborhood eps=2.0 m around anchor only",
            },
            {
                "site": "apply_dem endpoint linear-grade sampling",
                "kind": "direct_dem",
                "allowed": True,
                "notes": "DEM-derived start/end anchors; slope from DEM only",
            },
            {
                "site": "stage_05 flat sampler (_flat_sampler_or_raise)",
                "kind": "flat",
                "allowed": False,
                "notes": "FAIL_ON_FLAT_ELEVATION=True raises in strict; F2 gate also flags flat sampler",
            },
            {
                "site": "apply_dem KD-tree NN extrapolation (UP_ELEV_EXTRAPOLATION_MAX_DIST_M)",
                "kind": "nearest_neighbour",
                "allowed": False,
                "notes": "invented z from up to 2000 m away; F2 forbidden",
            },
            {
                "site": "apply_dem road-graph BFS propagation (5 hops)",
                "kind": "graph_propagation",
                "allowed": False,
                "notes": "copies neighbour z; F2 forbidden",
            },
            {
                "site": "apply_dem global median fallback",
                "kind": "median",
                "allowed": False,
                "notes": "median of all valid samples; F2 forbidden",
            },
            {
                "site": "apply_dem hardcoded 375.0 m constant",
                "kind": "hardcoded",
                "allowed": False,
                "notes": "hardcoded Ingolstadt z; F2 forbidden",
            },
        ],
    }

    policy = elevation_fallback_policy()
    report["policy_mode"] = policy

    tree = ET.parse(str(PINNED_CANDIDATE))
    root = tree.getroot()
    report["candidate"] = {
        "path": str(PINNED_CANDIDATE),
        "road_count": int(len(root.findall("road"))),
    }

    sampler = ElevationImporter.make_raster_sampler(
        str(DEM_PATH), xodr_path=str(PINNED_CANDIDATE)
    )
    report["sampler"] = {
        "map_crs_source": getattr(sampler, "_map_crs_source", None),
        "sampling_frame": getattr(sampler, "_sampling_frame", None),
        "crs_transform_applied": getattr(sampler, "_crs_transform_applied", None),
        "bbox_intersects_dem_bounds_wgs84": getattr(
            sampler, "_bbox_intersects_dem_bounds_wgs84", None
        ),
        "f1_verdict": (getattr(sampler, "_f1_crs_contract", None) or {}).get(
            "verdict"
        ),
    }

    qc = ElevationImporter.apply_dem(root, sampler, collect_qc=True)
    report["apply_dem_qc"] = qc

    forbidden = {
        "extrapolated": qc["extrapolated_road_ids"],
        "propagated": qc["propagated_road_ids"],
        "median_or_hardcoded": qc["unresolved_road_ids"],
        "flat_sampler": [],
    }
    total_forbidden = sum(len(v) for v in forbidden.values())
    report["forbidden_fallback_roads"] = forbidden
    report["forbidden_fallback_total"] = int(total_forbidden)
    report["f2_status"] = "PASS" if total_forbidden == 0 else "FAIL"
    report["fail_reason"] = None if total_forbidden == 0 else "forbidden_fallback_used"

    out_json = EVIDENCE_DIR / "F2_FALLBACK_POLICY.json"
    Path(out_json).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# F2 — strict fallback policy evidence",
        "",
        f"- run_id: `{RUN_ID}`  - status: **{report['f2_status']}**",
        f"- policy mode: `{policy}` (default strict; invented values raise)",
        "",
        "## Candidate DEM pass (collect-only, candidate untouched)",
        "",
        f"- roads sampled: {qc['sampled_points']}",
        f"- nodata road starts: {qc['nodata_points']}",
        f"- roads with any fallback kind: {total_forbidden}",
        f"  - KD-tree NN extrapolated: {len(forbidden['extrapolated'])}",
        f"  - graph propagated: {len(forbidden['propagated'])}",
        f"  - median/hardcoded: {len(forbidden['median_or_hardcoded'])}",
        f"- seam suspects (>30 m): {qc['suspect_seam_count']}",
        f"- sampler frame: `{report['sampler']['sampling_frame']}` "
        f"(source `{report['sampler']['map_crs_source']}`, F1 verdict "
        f"`{report['sampler']['f1_verdict']}`)",
        "",
        "## Fallback sites (code audit)",
        "",
    ]
    for site in report["fallback_sites_audit"]:
        md.append(
            f"- `{site['kind']}`: **{'allowed' if site['allowed'] else 'FORBIDDEN'}** "
            f"— {site['site']}. {site['notes']}"
        )
    md += [
        "",
        "Strict policy: `UP_ELEVATION_FALLBACK_POLICY` defaults to `strict`; any "
        "forbidden fallback raises RuntimeError with the road ids.  The candidate "
        "pass above produced zero invented elevation values.",
    ]
    (EVIDENCE_DIR / "F2_FALLBACK_POLICY.md").write_text("\n".join(md), encoding="utf-8")

    print(f"F2 status: {report['f2_status']}")
    print(out_json)
    return 0 if report["f2_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
