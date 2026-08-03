#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F1 — DEM provenance, validity, and coverage evidence.

Establishes, with evidence, for the frozen horizontal candidate:

1. CRS contract verdict (claimed header CRS vs verified Osm2Odr native frame)
2. True WGS84 map extent (planView in the verified frame)
3. DEM identity (SHA-256, CRS, vertical datum EGM2008, resolution, bounds,
   no-data, provider, licence) — downloading the full-extent Copernicus GLO-30
   (COP30) tile via OpenTopography when the map coverage requires it
4. Coverage gate (DEM must fully cover the map extent)

Fails closed (exit code 1) unless every gate passes.  Evidence is written to
reports/post_audit_hardening/<run_id>/F1_DEM_PROVENANCE.{json,md}.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T110000Z"
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
DEM_DIR = REPO_ROOT / "cities" / "ingolstadt" / "dem"
DEM_PATH = DEM_DIR / "dem_ing.tif"

DOWNLOAD_MARGIN_DEG = 0.01
DEM_PROVIDER = "COP30"
DEM_LICENCE = (
    "Copernicus DEM GLO-30 (Copernicus WorldDEM-30) distributed by "
    "OpenTopography; free of charge for all purposes under the Copernicus "
    "regulation policy."
)
DEM_DATUM = "EGM2008 (Copernicus DEM geoid-referenced heights)"


def main() -> int:
    from ultimate_pipeline.dem.dem_auto_downloader import download_dem_for_bounds
    from ultimate_pipeline.dem.dem_crs_contract import (
        map_wgs84_extent,
        osm_source_bounds,
        verify_crs_contract,
    )
    from ultimate_pipeline.dem.dem_identity import (
        dem_coverage_gate,
        dem_identity_record,
        dem_identity_valid,
        write_identity_report,
    )
    from ultimate_pipeline.config.settings import SETTINGS

    now = datetime.now(timezone.utc).isoformat()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_f1_dem_provenance.py",
        "generated_at_utc": now,
        "phase": "F",
        "f1_status": "PENDING",
    }

    # 1) OSM source bounds
    osm_bounds = osm_source_bounds(str(OSM_SOURCE))
    report["osm_source"] = {"path": str(OSM_SOURCE), "node_bounds_wgs84": osm_bounds}
    if osm_bounds is None:
        report["f1_status"] = "FAIL"
        report["fail_reason"] = "osm_source_unavailable"
        write_identity_report(report, str(EVIDENCE_DIR / "F1_DEM_PROVENANCE.json"))
        print(json.dumps(report, indent=2))
        return 1

    # 2) CRS contract verdict
    contract = verify_crs_contract(str(PINNED_CANDIDATE), osm_bounds)
    report["crs_contract"] = contract
    verdict = contract["verdict"]
    if verdict not in ("OSM2ODR_NATIVE_VERIFIED", "CLAIMED_CRS_VERIFIED"):
        report["f1_status"] = "FAIL"
        report["fail_reason"] = f"crs_contract:{verdict}"
        write_identity_report(report, str(EVIDENCE_DIR / "F1_DEM_PROVENANCE.json"))
        print(json.dumps(report, indent=2))
        return 1

    # 3) True WGS84 map extent (planView in the verified frame)
    extent = map_wgs84_extent(
        str(PINNED_CANDIDATE), osm_bounds=osm_bounds, strict=True
    )
    report["map_extent"] = extent
    if extent.get("extent_wgs84") is None:
        report["f1_status"] = "FAIL"
        report["fail_reason"] = "map_extent_unavailable"
        write_identity_report(report, str(EVIDENCE_DIR / "F1_DEM_PROVENANCE.json"))
        print(json.dumps(report, indent=2))
        return 1
    ext = extent["extent_wgs84"]

    # 4) DEM: download full extent if missing or if coverage fails
    coverage_precheck = None
    if DEM_PATH.exists():
        identity_precheck = dem_identity_record(
            str(DEM_PATH),
            provider=DEM_PROVIDER,
            licence=DEM_LICENCE,
            vertical_datum=DEM_DATUM,
            source="OpenTopography global DEM API (COP30)",
        )
        coverage_precheck = dem_coverage_gate(identity_precheck, ext)
    if not DEM_PATH.exists() or not bool(coverage_precheck and coverage_precheck.get("ok")):
        api_key = SETTINGS.OPENTOPO_API_KEY or os.getenv("OPENTOPO_API_KEY", "")
        if not api_key:
            report["f1_status"] = "FAIL"
            report["fail_reason"] = "opentopo_api_key_missing"
            write_identity_report(report, str(EVIDENCE_DIR / "F1_DEM_PROVENANCE.json"))
            print(json.dumps(report, indent=2))
            return 1
        download_dem_for_bounds(
            lat_min=ext["lat_min"] - DOWNLOAD_MARGIN_DEG,
            lat_max=ext["lat_max"] + DOWNLOAD_MARGIN_DEG,
            lon_min=ext["lon_min"] - DOWNLOAD_MARGIN_DEG,
            lon_max=ext["lon_max"] + DOWNLOAD_MARGIN_DEG,
            dem_type=DEM_PROVIDER,
            api_key=api_key,
            out_path=str(DEM_PATH),
        )
    report["dem_download"] = {
        "path": str(DEM_PATH),
        "download_margin_deg": DOWNLOAD_MARGIN_DEG,
        "already_present": bool(DEM_PATH.exists()),
        "existing_coverage_ok": bool(coverage_precheck and coverage_precheck.get("ok")),
    }

    # 5) DEM identity
    identity = dem_identity_record(
        str(DEM_PATH),
        provider=DEM_PROVIDER,
        licence=DEM_LICENCE,
        vertical_datum=DEM_DATUM,
        source="OpenTopography global DEM API (COP30)",
    )
    report["dem_identity"] = identity
    identity_ok = dem_identity_valid(identity)

    # 6) Coverage gate
    coverage = dem_coverage_gate(identity, ext) if identity_ok else {
        "ok": False,
        "reason": f"dem_identity:{identity.get('reason')}",
    }
    report["coverage_gate"] = coverage

    all_ok = bool(
        contract["verdict"] in ("OSM2ODR_NATIVE_VERIFIED", "CLAIMED_CRS_VERIFIED")
        and identity_ok
        and bool(coverage.get("ok", False))
    )
    report["f1_status"] = "PASS" if all_ok else "FAIL"
    report["fail_reason"] = None if all_ok else "gate_failed"

    out_json = EVIDENCE_DIR / "F1_DEM_PROVENANCE.json"
    write_identity_report(report, str(out_json))

    md = [
        "# F1 — DEM provenance, validity, and coverage",
        "",
        f"- run_id: `{RUN_ID}`  - status: **{report['f1_status']}**",
        f"- generated_at_utc: `{now}`",
        "",
        "## CRS contract",
        "",
        f"- verdict: **{contract['verdict']}** ({contract['reason']})",
        f"- claimed header CRS: `{contract['claimed_crs']}`",
        f"- claimed-CRS placement of header bounds (WGS84): "
        f"`{contract['claimed_crs_header_bounds_wgs84']}`",
        f"- verified native frame: `{contract['native_frame']}`",
        f"- native-frame placement of header bounds (WGS84): "
        f"`{contract['native_frame_header_bounds_wgs84']}`",
        f"- OSM source node bounds (WGS84): `{osm_bounds}`",
        f"- WP1 control point error under claimed CRS: "
        f"`{contract['wp1_control_point_error_m_if_claimed_crs']:.0f} m`",
        "",
        "## True map extent (WGS84)",
        "",
        f"- `{ext['lon_min']:.6f} .. {ext['lon_max']:.6f} E, "
        f"{ext['lat_min']:.6f} .. {ext['lat_max']:.6f} N`",
        f"- sampling CRS source: `{extent['sampling_crs_source']}`",
        "",
        "## DEM identity",
        "",
        f"- path: `{identity.get('path')}`",
        f"- SHA-256: `{identity.get('sha256')}`",
        f"- CRS: `{identity.get('crs')}`",
        f"- vertical datum: `{identity.get('vertical_datum')}`",
        f"- bounds (degrees): `{identity.get('bounds_degrees')}`",
        f"- resolution: `{identity.get('resolution_degrees')}`  "
        f"size: {identity.get('width')}x{identity.get('height')}",
        f"- no-data: `{identity.get('no_data')}`",
        f"- elevation min/max/mean: "
        f"{identity.get('elevation_min')}/{identity.get('elevation_max')}/"
        f"{identity.get('elevation_mean')} m",
        f"- provider: `{identity.get('provider')}`",
        f"- licence: `{identity.get('licence')}`",
        "",
        "## Coverage gate",
        "",
        f"- verdict: **{coverage.get('ok')}** ({coverage.get('reason')})",
        f"- DEM bounds vs map extent overlap: `{coverage.get('overlap_wgs84')}`",
        "",
        "F1 gates (CRS contract resolvable, DEM identity complete, full map "
        "coverage) must ALL pass before F2..F7 may proceed.",
    ]
    (EVIDENCE_DIR / "F1_DEM_PROVENANCE.md").write_text(
        "\n".join(md), encoding="utf-8"
    )
    print(f"F1 status: {report['f1_status']}")
    print(out_json)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
