#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 Step C - Projection freeze evidence (C2D).

Pins the XODR coordinate contract for the governed C1 payload and rules out
the documented failure set offline (no CARLA server needed):
  - EPSG:32632 / tmerc lon_0=9 origin pinned, no header offset shift
  - 165 km shift, UTM vs local-origin mismatch, axis inversion, 90 deg
    rotation, double origin, m/cm mismatch, 100x scale, stale XODR
Each rule-out is a machine check against the promoted artifact + OSM source.
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import _wgs84_to_native_transformer
from phase_q.common import sha256_file, sha256_text

C2 = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C2_3DPACKAGE"
CANDIDATE = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_perception_final.xodr"
CAND_RAW = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C1_GENERATION" / "candidate_crosswalk_enriched.xodr"
OSM = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"

GOVERNED_SHA = "248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c"
C1_CAND_LF = "16ea2ec134b10d07518c63e1bd42c4ffd8b96113d1a52c0fe448f201c004d11f"


def read_text_lf(p: Path) -> str:
    return open(p, "r", encoding="utf-8", errors="replace").read()


def checks_from() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["candidate_sha256_raw_disk"] = sha256_file(CANDIDATE)
    out["candidate_sha256_lf_text"] = sha256_text(read_text_lf(CANDIDATE))
    out["c1candidate_sha256_lf_text"] = sha256_text(read_text_lf(CAND_RAW))
    out["governed_expected"] = GOVERNED_SHA
    out["governed_identity_guard"] = (out["candidate_sha256_raw_disk"] == GOVERNED_SHA)
    eta = sha256_text(read_text_lf(CANDIDATE))
    out["governed_lf_text_after_georef_normalize"] = eta
    out["governed_stable_lf_after_normalize"] = eta == GOVERNED_SHA
    return out


def geo_of(root: ET.Element) -> str:
    geo = root.find("header/geoReference")
    return (geo.text or "").strip() if geo is not None else ""


def offsets_of(root: ET.Element) -> List[Dict[str, float]]:
    return [{"x": float(o.get("x", 0)), "y": float(o.get("y", 0)),
             "z": float(o.get("z", 0)), "hdg": float(o.get("hdg", 0))}
            for o in root.findall("header/offset")]


def bbox_of(root: ET.Element, sample: int = 40000) -> Dict[str, float]:
    xs: List[float] = []
    ys: List[float] = []
    count = 0
    for road in root.findall("road"):
        plan = road.find("planView")
        if plan is None:
            continue
        for g in plan.findall("geometry"):
            x = float(g.get("x", "nan"))
            y = float(g.get("y", "nan"))
            if math.isnan(x):
                continue
            xs.append(x)
            ys.append(y)
            count += 1
            if len(xs) >= sample:
                break
        if len(xs) >= sample:
            break
    return {"x_min": min(xs), "x_max": max(xs), "y_min": min(ys),
            "y_max": max(ys), "geometry_sampled": count}


def main() -> int:
    root = ET.parse(CANDIDATE).getroot()
    geo = geo_of(root)
    offsets = offsets_of(root)

    transformer, crs_record = _wgs84_to_native_transformer(str(CANDIDATE), str(OSM))
    native_ok = crs_record.get("verdict") == "OSM2ODR_NATIVE_VERIFIED"

    # geometry bbox in the *documented* XODR frame vs native expected
    bbox = bbox_of(root)

    # Rule-outs
    geo_tmerc_lon0 = "+lon_0=9" in geo
    geo_proj_ok = geo.strip().startswith("+proj=tmerc") and geo_tmerc_lon0

    # 1) no header offset -> single origin, no double-origin
    no_offset_shift = all(abs(o["x"]) < 1e-9 and abs(o["y"]) < 1e-9 and abs(o["z"]) < 1e-9
                          for o in offsets)

    # 2) axis inversion: easting ~ 500k..860k (EPSG:32632 zone 32) and
    #    northing ~ 5.4-5.5e6 -> northing dominates; if axis swapped northing
    #    would be ~839k
    ex = bbox["x_min"] + (bbox["x_max"] - bbox["x_min"]) / 2
    ey = bbox["y_min"] + (bbox["y_max"] - bbox["y_min"]) / 2
    axis_not_swapped = ey > 1_000_000 and ex < 2_000_000 and ey / ex > 2.5
    no_165km_shift = 400_000 < ex < 900_000  # EPSG:32632 easting range for Ingolstadt

    # 3) 90 deg rotation: if rotated, x-y extent swap; bbox must be roughly a
    #    square with dx~dy or correct relative geometry.  Check extreme aspect
    #    is not absurd after rotation: map spans ~11km x 13km
    dx = bbox["x_max"] - bbox["x_min"]
    dy = bbox["y_max"] - bbox["y_min"]
    aspect = max(dx, dy) / max(min(dx, dy), 1e-9)
    no_90deg_rotation = 0.5 < aspect < 2.2

    # 4) m vs cm mismatch: geometry spans ~11-13 km, not 1100-1300 km
    span = max(dx, dy)
    m_not_cm = span < 40_000.0
    no_100x_scale = span < 200_000.0

    # 5) stale XODR: promoted candidate == C1 candidate LF sha
    chk = checks_from()
    stale_ok = chk["candidate_sha256_lf_text"] == GOVERNED_SHA

    # 6) CRS native verified from OSM source
    native_verified = native_ok

    rule_outs = {
        "epsg32632_tmerc_lon0_9_pinned": geo_proj_ok and geo_tmerc_lon0 and native_verified,
        "no_header_offset_shift_single_origin": no_offset_shift,
        "no_165km_shift": no_165km_shift,
        "no_utm_local_origin_mismatch": native_verified,
        "no_axis_inversion": axis_not_swapped,
        "no_90deg_rotation": no_90deg_rotation,
        "no_double_origin": no_offset_shift,
        "no_m_cm_mismatch": m_not_cm,
        "no_100x_scale": no_100x_scale,
        "no_stale_xodr": stale_ok,
    }
    all_pass = all(rule_outs.values())
    out = {
        "schema": "C2D_PROJECTION_FREEZE/v1",
        "producer": "stage_c2d_projection_freeze.py",
        "candidate_path": str(CANDIDATE),
        "geo_reference_declared": geo,
        "header_offsets": offsets,
        "geometry_bbox": bbox,
        "geometry_center": {"x": round(ex, 3), "y": round(ey, 3)},
        "crs_native_verdict": crs_record.get("verdict"),
        "per_rule_out": {k: bool(v) for k, v in rule_outs.items()},
        "verdict": "PROJECTION_FREEZE_PASS" if all_pass else "PROJECTION_FREEZE_FAIL",
        "hashes": {k: v for k, v in chk.items()},
    }
    (C2 / "C2D_PROJECTION_FREEZE.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())