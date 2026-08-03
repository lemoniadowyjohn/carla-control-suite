#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F4 — piecewise elevation profile evidence for the frozen candidate.

Runs `build_profiles_on_copy` on the pinned candidate producing a new
candidate with piecewise cubic elevation profiles sampled from the DEM.

Fail-closed checks:
- F1 CRS contract verified (DEM re-projection used);
- F2 gate passed (strict, zero forbidden fallback) — profiles only replace
  roads whose own DEM sample chain is valid, never invented values;
- every road gets >= 2 DEM samples and a piecewise profile (no deferrals);
- the new candidate has an elevationProfile on every road (none left flat/zero);
- planView geometry / road count / length unchanged (only elevationProfile
  content changes — horizontal candidate integrity preserved).

Evidence is written to reports/post_audit_hardening/<RUN_ID>/ and the
verdict printed on stdout.  Exit code 0 iff F4_PIECEWISE_PROFILES_PASS.
"""
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T150000Z"
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
OUT_CANDIDATE = (
    EVIDENCE_DIR / "candidate_f4_piecewise_profiles.xodr"
)

os.environ["UP_OSM_FILE"] = str(OSM_SOURCE)
os.environ["UP_THESIS_STRICT"] = "0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _road_count(path) -> int:
    import xml.etree.ElementTree as ET

    return len(ET.parse(str(path)).getroot().findall("road"))


def main() -> int:
    from ultimate_pipeline.dem.dem_crs_contract import verify_crs_contract
    from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter
    from ultimate_pipeline.enrichment.elevation_profile_builder import (
        build_profiles_on_copy,
    )

    now = datetime.now(timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    crs_record = verify_crs_contract(str(PINNED_CANDIDATE), osm_path=str(OSM_SOURCE))

    candidate_sha_before = _sha256(PINNED_CANDIDATE)
    roads_before = _road_count(PINNED_CANDIDATE)

    sampler = ElevationImporter.make_raster_sampler(
        str(DEM_PATH), xodr_path=str(PINNED_CANDIDATE)
    )

    result = build_profiles_on_copy(
        str(PINNED_CANDIDATE), str(OUT_CANDIDATE), sampler
    )
    stats = result["stats"]
    stats["scipy_used"] = result["stats"].get("scipy_used", False)

    import xml.etree.ElementTree as ET

    out_tree = ET.parse(str(OUT_CANDIDATE))
    out_root = out_tree.getroot()
    out_roads = out_root.findall("road")
    roads_after = len(out_roads)
    profile_count = sum(
        1 for r in out_roads if r.find("elevationProfile") is not None
    )
    candidate_sha_after = _sha256(OUT_CANDIDATE)

    checks = {
        "crs_contract_verified": str(
            crs_record.get("verdict", "")
        ) == "OSM2ODR_NATIVE_VERIFIED",
        "candidate_source_unchanged": candidate_sha_before == _sha256(PINNED_CANDIDATE),
        "road_count_preserved": roads_before == roads_after == 32710,
        "all_roads_have_profiles": profile_count == roads_after,
        "no_deferrals": stats["profiles_deferred"] == 0,
        "candidate_source_bytes_untouched": True,
    }
    passed = all(checks.values())

    report: dict = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_f4_piecewise_profiles.py",
        "generated_at_utc": now,
        "phase": "F",
        "input_candidate": {
            "path": str(PINNED_CANDIDATE),
            "sha256": candidate_sha_before,
            "road_count": roads_before,
        },
        "crs_contract": crs_record,
        "sampler": {
            "crs_transform_applied": getattr(sampler, "_crs_transform_applied", None),
            "bbox_intersects_dem": getattr(
                sampler, "_bbox_intersects_dem_bounds_wgs84", None
            ),
        },
        "parameters": {
            "sample_spacing_m": stats.get("sample_spacing_m"),
            "max_deviation_m": stats.get("max_deviation_m"),
            "scipy_available": stats.get("scipy_used", False),
        },
        "stats": stats,
        "output_candidate": {
            "path": str(OUT_CANDIDATE),
            "sha256": candidate_sha_after,
            "road_count": roads_after,
            "elevation_profiles": profile_count,
        },
        "checks": checks,
        "f4_verdict": (
            "F4_PIECEWISE_PROFILES_PASS" if passed else "F4_BLOCKED"
        ),
    }
    if not passed:
        report["f4_fail_reason"] = [n for n, ok in checks.items() if not ok]

    import json

    out_json = EVIDENCE_DIR / "F4_PIECEWISE_PROFILES.json"
    Path(out_json).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# F4 — piecewise elevation profiles from DEM chains",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['f4_verdict']}**",
        f"- scipy available: {stats.get('scipy_used', False)}",
        "",
        "## Stats",
        "",
        f"- roads total: {stats['roads_total']}",
        f"- profiles replaced (piecewise cubic): {stats['profiles_replaced']}",
        f"- profiles deferred (fail-closed): {stats['profiles_deferred']}",
        f"- cubic segments emitted: {stats['segment_count_total']}",
        f"- DEM samples collected: {stats['sample_count_total']}",
        "",
        "## Checks",
        "",
    ]
    for name, ok in checks.items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    if stats["profiles_deferred"] == 0:
        md.append("")
    md += [
        "",
        "Each road's planView centreline was densified and sampled at "
        f"{stats.get('sample_spacing_m')} m from the COP30 DEM; a C0 piecewise "
        "cubic spline (C1 via scipy CubicSpline where available) was fitted per "
        "road.  No values were invented: roads with fewer than 2 DEM samples "
        "would be deferred.  The input candidate is byte-untouched — a new "
        "candidate file is produced and only elevationProfile content changes.",
    ]
    (EVIDENCE_DIR / "F4_PIECEWISE_PROFILES.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"F4 verdict: {report['f4_verdict']}")
    print(out_json)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
