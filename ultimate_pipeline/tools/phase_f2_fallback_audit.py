#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F2 — strict fallback policy evidence.

Runs the DEM elevation pass against the frozen horizontal candidate in BOTH
policy modes without writing elevation anywhere (collect-only):

- strict (default): any forbidden fallback (NN extrapolation, graph
  propagation, median, hardcoded 375.0, flat sampler, endpoint no-data)
  raises RuntimeError — the run must complete with zero violations.
- audit: records every forbidden attempt and returns QC evidence without
  mutating the candidate.

The candidate file is never touched.  Env is set before any settings import
(SETTINGS is constructed at import time).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T130000Z"
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
# import time).  Evidence run must never write elevation: the candidate file
# is never touched, collect_qc returns evidence only.
os.environ["UP_OSM_FILE"] = str(OSM_SOURCE)
os.environ["UP_THESIS_STRICT"] = "0"


def _fallback_sites_audit() -> list:
    return [
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
            "site": "apply_dem endpoint no-data (linear grade)",
            "kind": "endpoint_nodata",
            "allowed": False,
            "notes": "endpoint cannot be sampled -> structured violation; no flat substitution",
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
    ]


def _run_mode(mode: str) -> dict:
    os.environ["UP_ELEVATION_FALLBACK_POLICY"] = mode
    from ultimate_pipeline.config.settings import SETTINGS  # noqa: F401
    from ultimate_pipeline.enrichment.elevation_fallback_policy import (
        elevation_fallback_policy,
    )
    from ultimate_pipeline.enrichment.elevation_importer import (
        ElevationImporter,
    )

    policy = elevation_fallback_policy()
    record: dict = {
        "requested_mode": mode,
        "resolved_policy": policy,
        "status": "PENDING",
        "candidate_sha256_before": _sha256(PINNED_CANDIDATE),
    }
    tree = ET.parse(str(PINNED_CANDIDATE))
    root = tree.getroot()
    record["candidate"] = {
        "path": str(PINNED_CANDIDATE),
        "road_count": int(len(root.findall("road"))),
        "sha256_before": record["candidate_sha256_before"],
    }

    sampler = ElevationImporter.make_raster_sampler(
        str(DEM_PATH), xodr_path=str(PINNED_CANDIDATE)
    )
    record["sampler"] = {
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

    try:
        qc = ElevationImporter.apply_dem(root, sampler, collect_qc=True)
        record["apply_dem_qc"] = qc
        forbidden = {
            "extrapolated": qc["extrapolated_road_ids"],
            "propagated": qc["propagated_road_ids"],
            "median_or_hardcoded": qc["unresolved_road_ids"],
            "flat_sampler": [],
            "endpoint_nodata": qc.get("endpoint_nodata_road_ids", []),
        }
        total_forbidden = sum(len(v) for v in forbidden.values())
        record["forbidden_fallback_roads"] = forbidden
        record["forbidden_fallback_total"] = int(total_forbidden)
        record["status"] = "PASS" if total_forbidden == 0 else "FAIL"
        record["fail_reason"] = (
            None if total_forbidden == 0 else "forbidden_fallback_used"
        )
    except RuntimeError as exc:
        record["status"] = "FAIL"
        record["fail_reason"] = "strict_raise"
        record["strict_error"] = str(exc)
    record["candidate_sha256_after"] = _sha256(PINNED_CANDIDATE)
    return record


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modes",
        default="strict,audit",
        help="comma-separated modes to run (strict, audit, lenient)",
    )
    args = parser.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    now = datetime.now(timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_f2_fallback_audit.py",
        "generated_at_utc": now,
        "phase": "F",
        "fallback_sites_audit": _fallback_sites_audit(),
        "modes": {},
    }
    for mode in modes:
        report["modes"][mode] = _run_mode(mode)

    strict = report["modes"].get("strict", {})
    audit = report["modes"].get("audit", {})
    strict_ok = strict.get("status") == "PASS"
    audit_ok = audit.get("status") == "PASS" and audit.get("forbidden_fallback_total") == 0
    report["f2_verdict"] = "F2_STRICT_AND_AUDIT_PASS" if (strict_ok and audit_ok) else "F2_BLOCKED"
    if not strict_ok:
        report["f2_fail_reason"] = f"strict: {strict.get('fail_reason')}"
    elif not audit_ok:
        report["f2_fail_reason"] = f"audit: {audit.get('fail_reason')}"

    out_json = EVIDENCE_DIR / "F2_FALLBACK_POLICY.json"
    Path(out_json).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# F2 — strict fallback policy evidence",
        "",
        f"- run_id: `{RUN_ID}`  - verdict: **{report['f2_verdict']}**",
        "- strict mode is the default; `UP_ELEVATION_FALLBACK_POLICY` may set",
        "  `strict` | `audit` | `lenient`.",
        "",
        "## Modes",
        "",
    ]
    for mode, rec in report["modes"].items():
        qc = rec.get("apply_dem_qc") or {}
        md += [
            f"### `{mode}`  — **{rec['status']}**",
            "",
            f"- resolved policy: `{rec['resolved_policy']}`",
            f"- roads sampled: {qc.get('sampled_points')}",
            f"- nodata road starts: {qc.get('nodata_points')}",
            f"- forbidden fallback total: {rec.get('forbidden_fallback_total')}",
            f"  - KD-tree NN extrapolated: "
            f"{len(rec.get('forbidden_fallback_roads', {}).get('extrapolated', []))}",
            f"  - graph propagated: "
            f"{len(rec.get('forbidden_fallback_roads', {}).get('propagated', []))}",
            f"  - median/hardcoded: "
            f"{len(rec.get('forbidden_fallback_roads', {}).get('median_or_hardcoded', []))}",
            f"  - endpoint no-data: "
            f"{len(rec.get('forbidden_fallback_roads', {}).get('endpoint_nodata', []))}",
            f"- seam suspects (>30 m): {qc.get('suspect_seam_count')}",
            f"- candidate sha256 unchanged: "
            f"{rec.get('candidate_sha256_before') == rec.get('candidate_sha256_after')}",
            "",
        ]
        if rec.get("strict_error"):
            md += ["strict error (expected to block):", "", "```", rec["strict_error"], "```", ""]
    md += [
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
        "In strict mode every unavailable DEM sample becomes a structured "
        "violation; no synthetic elevation is inserted and the run raises.  "
        "In audit mode every forbidden attempt is recorded without mutating "
        "the candidate.  `collect_qc` never bypasses the F2 gate (the gate "
        "runs before the QC return).",
    ]
    (EVIDENCE_DIR / "F2_FALLBACK_POLICY.md").write_text("\n".join(md), encoding="utf-8")

    print(f"F2 verdict: {report['f2_verdict']}")
    print(out_json)
    return 0 if report["f2_verdict"] == "F2_STRICT_AND_AUDIT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
