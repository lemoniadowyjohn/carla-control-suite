#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F1 — DEM identity, validity, and coverage gate.

Establishes DEM identity (path, SHA-256, CRS, vertical datum, bounds,
resolution, no-data, provider, licence) and verifies it covers the true
WGS84 extent of the candidate map before any elevation sampling may run.

Fail-closed policy:

- rasterio unavailable or file unreadable        -> FAIL
- vertical datum unknown                          -> FAIL (identity incomplete)
- DEM bounds do not fully cover the map extent    -> FAIL (coverage gate)
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import rasterio  # type: ignore
except Exception:
    rasterio = None  # type: ignore

from ultimate_pipeline.dem.dem_provenance import (
    DEMProvenance,
    record_dem_provenance,
    save_dem_provenance,
    verify_dem_provenance,
)


def dem_identity_record(
    dem_path: str,
    *,
    provider: str,
    licence: str,
    vertical_datum: str,
    source: str = "",
) -> Dict[str, Any]:
    """Full identity record for a DEM GeoTIFF; fail closed on any gap."""
    if rasterio is None:
        return {"ok": False, "reason": "rasterio_unavailable"}
    if not os.path.isfile(dem_path):
        return {"ok": False, "reason": "file_missing", "path": dem_path}
    try:
        with rasterio.open(dem_path) as ds:
            crs = str(ds.crs)
            bounds = {
                "left": float(ds.bounds.left),
                "bottom": float(ds.bounds.bottom),
                "right": float(ds.bounds.right),
                "top": float(ds.bounds.top),
            }
            res = {"x": float(ds.res[0]), "y": float(ds.res[1])}
            nodata = ds.nodata
            band = ds.read(1, masked=True)
            valid = int(band.count()) if hasattr(band, "count") else None
            elev_min = float(band.min()) if valid and valid > 0 else None
            elev_max = float(band.max()) if valid and valid > 0 else None
            elev_mean = (
                float(band.mean()) if valid and valid > 0 else None
            )
            width = ds.width
            height = ds.height
    except Exception as exc:
        return {"ok": False, "reason": f"open_failed:{exc}", "path": dem_path}

    provenance = record_dem_provenance(
        dem_path,
        crs=crs,
        vertical_datum=vertical_datum,
        bounds=bounds,
        resolution_m=None,
        no_data=nodata,
        provider=provider,
        licence=licence,
    )

    record = {
        "ok": True,
        "path": os.path.abspath(dem_path),
        "sha256": provenance.sha256,
        "file_bytes": provenance.file_bytes,
        "crs": crs,
        "vertical_datum": vertical_datum,
        "bounds_degrees": bounds,
        "bounds_wgs84": {
            "lon_min": bounds["left"],
            "lat_min": bounds["bottom"],
            "lon_max": bounds["right"],
            "lat_max": bounds["top"],
        },
        "resolution_degrees": res,
        "width": width,
        "height": height,
        "no_data": nodata,
        "provider": provider,
        "licence": licence,
        "source": source,
        "valid_pixel_count": valid,
        "elevation_min": elev_min,
        "elevation_max": elev_max,
        "elevation_mean": elev_mean,
        "provenance": provenance.to_dict(),
    }
    return record


def _deg_to_m(lon0: float, lat0: float, lon1: float, lat1: float) -> float:
    dlat = (lat1 - lat0) * 110540.0
    dlon = (lon1 - lon0) * 111320.0 * math.cos(math.radians((lat0 + lat1) / 2.0))
    return math.hypot(dlon, dlat)


def dem_coverage_gate(
    identity: Dict[str, Any],
    map_extent_wgs84: Dict[str, Any],
    *,
    margin_deg: float = 0.0,
) -> Dict[str, Any]:
    """Coverage verdict: DEM must fully cover the map WGS84 extent."""
    if not identity.get("ok", False):
        return {"ok": False, "reason": f"dem_identity:{identity.get('reason')}"}
    if map_extent_wgs84 is None:
        return {"ok": False, "reason": "map_extent_unavailable"}
    dem_b = identity["bounds_wgs84"]
    me = map_extent_wgs84

    needed = {
        "lon_min": me["lon_min"] - margin_deg,
        "lat_min": me["lat_min"] - margin_deg,
        "lon_max": me["lon_max"] + margin_deg,
        "lat_max": me["lat_max"] + margin_deg,
    }
    fully_covered = bool(
        dem_b["lon_min"] <= needed["lon_min"]
        and dem_b["lat_min"] <= needed["lat_min"]
        and dem_b["lon_max"] >= needed["lon_max"]
        and dem_b["lat_max"] >= needed["lat_max"]
    )
    overlap = {
        "lon_min": max(dem_b["lon_min"], me["lon_min"]),
        "lat_min": max(dem_b["lat_min"], me["lat_min"]),
        "lon_max": min(dem_b["lon_max"], me["lon_max"]),
        "lat_max": min(dem_b["lat_max"], me["lat_max"]),
    }
    map_w = _deg_to_m(
        me["lon_min"], me["lat_min"], me["lon_max"], me["lat_max"]
    )
    inter_w = 0.0
    if (
        overlap["lon_max"] > overlap["lon_min"]
        and overlap["lat_max"] > overlap["lat_min"]
    ):
        inter_w = _deg_to_m(
            overlap["lon_min"], overlap["lat_min"],
            overlap["lon_max"], overlap["lat_max"],
        )
    coverage_ratio = (inter_w / map_w) if map_w > 0 else 0.0

    return {
        "ok": bool(fully_covered),
        "fully_covered": bool(fully_covered),
        "dem_bounds_wgs84": dem_b,
        "map_extent_wgs84": me,
        "needed_bounds_wgs84": needed,
        "overlap_wgs84": overlap,
        "coverage_ratio_diag": coverage_ratio,
        "margin_deg": margin_deg,
        "reason": "covered" if fully_covered else "map_extent_not_covered",
    }


def dem_identity_valid(
    identity: Dict[str, Any],
    *,
    required_fields: tuple = ("crs", "vertical_datum", "sha256"),
) -> bool:
    if not identity.get("ok", False):
        return False
    for field in required_fields:
        if not identity.get(field):
            return False
    return True


def write_identity_report(record: Dict[str, Any], out_json: str) -> str:
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
    return out_json


def verify_identity_file(identity: Dict[str, Any]) -> Dict[str, Any]:
    prov = DEMProvenance.from_dict(identity.get("provenance", {}))
    return verify_dem_provenance(prov)
