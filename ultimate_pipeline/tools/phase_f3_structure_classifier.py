#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F3 — road structure classification evidence for the frozen candidate.

Runs `classify_xodr_roads` (spatial matching against authoritative OSM
structure ways in the F1-verified Osm2Odr native frame) and gates DEM
application on the classification identity.

Fail-closed checks:
- F1 CRS contract must verify (OSM2ODR_NATIVE_VERIFIED) before projection;
- classification verdict must be STRUCTURE_CLASSIFICATION_OK;
- the structure gate must PASS (identity established) without raising;
- every `unknown` road must resolve to the fail_closed profile policy
  (no ground-DEM forcing on unidentified roads);
- the candidate file must be byte-identical before/after (never mutated).

Evidence is written to reports/post_audit_hardening/<RUN_ID>/ and the
verdict printed on stdout.  Exit code 0 iff F3_STRUCTURE_CLASSIFICATION_PASS.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T140000Z"
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

# Env must be set BEFORE any settings import (SETTINGS is constructed at
# import time).  The evidence run never mutates the candidate.
os.environ["UP_OSM_FILE"] = str(OSM_SOURCE)
os.environ["UP_THESIS_STRICT"] = "0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--class-fraction", type=float, default=0.60)
    parser.add_argument("--buffer-m", type=float, default=12.0)
    parser.add_argument("--sample-spacing-m", type=float, default=4.0)
    args = parser.parse_args()

    from ultimate_pipeline.dem.dem_crs_contract import verify_crs_contract
    from ultimate_pipeline.enrichment.structure_classifier import (
        UNKNOWN,
        apply_dem_structure_gate,
        classify_xodr_roads,
        structure_profile_policy,
        structure_road_ids,
    )

    now = datetime.now(timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    crs_record = verify_crs_contract(str(PINNED_CANDIDATE), osm_path=str(OSM_SOURCE))
    candidate_sha_before = _sha256(PINNED_CANDIDATE)
    classification = classify_xodr_roads(
        str(PINNED_CANDIDATE),
        osm_path=str(OSM_SOURCE),
        buffer_m=args.buffer_m,
        class_fraction=args.class_fraction,
        sample_spacing_m=args.sample_spacing_m,
    )
    candidate_sha_after = _sha256(PINNED_CANDIDATE)
    candidate_unchanged = candidate_sha_before == candidate_sha_after

    gate = apply_dem_structure_gate(classification, strict=True)
    class_counts = classification.get("class_counts", {})
    unknown_roads = [
        rid
        for rid, rec in classification.get("per_road", {}).items()
        if rec.get("class") == UNKNOWN
    ]
    unknown_policy = (
        structure_profile_policy(UNKNOWN)
        if unknown_roads
        else "n/a (no unknown roads)"
    )
    unknown_fail_closed = unknown_policy == "fail_closed" or not unknown_roads

    checks = {
        "candidate_sha256_unchanged": candidate_unchanged,
        "classification_ok": classification.get("verdict") == "STRUCTURE_CLASSIFICATION_OK",
        "roads_total_equals_frozen": classification.get("roads_total") == 32710,
        "structure_identity_established": bool(
            set(class_counts) & {"bridge", "tunnel", "underpass", "covered",
                                 "embankment", "cutting", "elevated"}
        ),
        "structure_gate_passed": gate.get("gate") == "PASS",
        "unknown_fail_closed_policy": unknown_fail_closed,
    }
    passed = all(checks.values())

    report: dict = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_f3_structure_classifier.py",
        "generated_at_utc": now,
        "phase": "F",
        "candidate": {
            "path": str(PINNED_CANDIDATE),
            "sha256_before": candidate_sha_before,
            "sha256_after": candidate_sha_after,
            "sha256_unchanged": candidate_unchanged,
        },
        "crs_contract": crs_record,
        "roads_total": classification.get("roads_total"),
        "class_counts": class_counts,
        "matched_structure_ways": {
            "matched": len(classification.get("structure_way_ids_matched", [])),
            "total_ways": classification.get("structure_ways", {}).get(
                "structure_ways_total", 0
            ),
            "counts_per_class": classification.get("structure_ways", {}).get(
                "counts_per_class", {}
            ),
            "way_ids_matched": classification.get("structure_way_ids_matched", []),
        },
        "matched_length_m": classification.get("matched_length_m"),
        "total_length_m": classification.get("total_length_m"),
        "matched_fraction": classification.get("matched_fraction"),
        "deck_linear_road_ids": structure_road_ids(classification),
        "unknown_road_count": len(unknown_roads),
        "unknown_road_ids": unknown_roads,
        "unknown_profile_policy": unknown_policy,
        "structure_gate": gate,
        "parameters": {
            "class_fraction": args.class_fraction,
            "buffer_m": args.buffer_m,
            "sample_spacing_m": args.sample_spacing_m,
        },
        "checks": checks,
        "f3_verdict": (
            "F3_STRUCTURE_CLASSIFICATION_PASS"
            if passed
            else "F3_STRUCTURE_CLASSIFICATION_BLOCKED"
        ),
    }
    if not passed:
        report["f3_fail_reason"] = [
            name for name, ok in checks.items() if not ok
        ]

    out_json = EVIDENCE_DIR / "F3_STRUCTURE_CLASSIFICATION.json"
    Path(out_json).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# F3 — road structure classification evidence",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['f3_verdict']}**",
        f"- candidate: `{PINNED_CANDIDATE.name}` (sha256 unchanged: {candidate_unchanged})",
        f"- roads classified: {report['roads_total']}",
        "",
        "## Class counts",
        "",
        "| class | roads | profile policy |",
        "|---|---|---|",
    ]
    for cls in sorted(class_counts):
        md.append(
            f"| {cls} | {class_counts[cls]} | "
            f"`{structure_profile_policy(cls)}` |"
        )
    md += [
        "",
        "## Checks",
        "",
    ]
    for name, ok in checks.items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        f"- matched structure ways: "
        f"{report['matched_structure_ways']['matched']} / "
        f"{report['matched_structure_ways']['total_ways']}",
        f"- matched centreline length: {report['matched_length_m']} m "
        f"({report['matched_fraction']:.4f} of {report['total_length_m']} m)",
        f"- deck_linear (never ground-DEM forced) roads: "
        f"{len(report['deck_linear_road_ids'])}",
        f"- unknown roads: {report['unknown_road_count']} "
        f"(profile policy: `{report['unknown_profile_policy']}`)",
        "",
        "Classification never mutates the XODR document; the structure gate "
        "must PASS (fail-closed) before any DEM application, and unidentified "
        "roads resolve to the fail_closed profile policy.",
    ]
    (EVIDENCE_DIR / "F3_STRUCTURE_CLASSIFICATION.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"F3 verdict: {report['f3_verdict']}")
    print(out_json)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
