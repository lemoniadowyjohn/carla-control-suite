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

try:
    from pyproj import Transformer, CRS
except Exception:
    Transformer = None  # type: ignore
    CRS = None  # type: ignore

from ultimate_pipeline.dem.dem_provenance import (
    DEMProvenance,
    record_dem_provenance,
    save_dem_provenance,
    verify_dem_provenance,
)


def _transform_bounds_to_wgs84(
    bounds: Dict[str, float], src_crs: str
) -> Optional[Dict[str, float]]:
    """Transform bounds from source CRS to WGS84 (EPSG:4326)."""
    if Transformer is None or CRS is None:
        return None
    try:
        src = CRS.from_user_input(src_crs)
        dst = CRS.from_epsg(4326)
        tf = Transformer.from_crs(src, dst, always_xy=True)
    except Exception:
        return None

    try:
        corners = [
            (float(bounds["left"]), float(bounds["bottom"])),
            (float(bounds["left"]), float(bounds["top"])),
            (float(bounds["right"]), float(bounds["bottom"])),
            (float(bounds["right"]), float(bounds["top"])),
        ]
        tx = []
        ty = []
        for x, y in corners:
            xx, yy = tf.transform(x, y)
            tx.append(float(xx))
            ty.append(float(yy))
    except Exception:
        return None

    return {
        "lon_min": min(tx),
        "lat_min": min(ty),
        "lon_max": max(tx),
        "lat_max": max(ty),
    }


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
        resolution_m=res["x"],
        no_data=nodata,
        provider=provider,
        licence=licence,
        verify_against_raster=True,
    )

    if provenance._provenance_mismatches:
        return {
            "ok": False,
            "reason": "provenance_mismatch",
            "path": dem_path,
            "provenance_mismatches": provenance._provenance_mismatches,
        }

    # Transform bounds to WGS84 if CRS is available
    bounds_wgs84 = _transform_bounds_to_wgs84(bounds, crs)
    if bounds_wgs84 is None:
        # Fallback: if transformation fails, mark as unavailable
        bounds_wgs84 = {
            "lon_min": None,
            "lat_min": None,
            "lon_max": None,
            "lat_max": None,
        }

    record = {
        "ok": True,
        "path": os.path.abspath(dem_path),
        "sha256": provenance.sha256,
        "file_bytes": provenance.file_bytes,
        "crs": crs,
        "vertical_datum": provenance.vertical_datum,
        "vertical_datum_source": provenance._vertical_datum_source,
        "bounds_native": bounds,
        "bounds_wgs84": bounds_wgs84,
        "resolution_native": res,
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


def _rect_area_m2(bounds: Dict[str, float]) -> float:
    """Compute approximate area in m² of a WGS84 bounding box."""
    if None in (bounds.get("lon_min"), bounds.get("lat_min"), bounds.get("lon_max"), bounds.get("lat_max")):
        return 0.0
    # Approximate: width * height at center latitude
    center_lat = (bounds["lat_min"] + bounds["lat_max"]) / 2.0
    dx = (bounds["lon_max"] - bounds["lon_min"]) * 111320.0 * math.cos(math.radians(center_lat))
    dy = (bounds["lat_max"] - bounds["lat_min"]) * 110540.0
    return max(0.0, dx * dy)


def _rect_intersection(b1: Dict[str, float], b2: Dict[str, float]) -> Optional[Dict[str, float]]:
    """Return intersection of two WGS84 bounding boxes."""
    if None in (b1.get("lon_min"), b1.get("lat_min"), b1.get("lon_max"), b1.get("lat_max"),
                b2.get("lon_min"), b2.get("lat_min"), b2.get("lon_max"), b2.get("lat_max")):
        return None
    lon_min = max(b1["lon_min"], b2["lon_min"])
    lat_min = max(b1["lat_min"], b2["lat_min"])
    lon_max = min(b1["lon_max"], b2["lon_max"])
    lat_max = min(b1["lat_max"], b2["lat_max"])
    if lon_max <= lon_min or lat_max <= lat_min:
        return None
    return {"lon_min": lon_min, "lat_min": lat_min, "lon_max": lon_max, "lat_max": lat_max}


def dem_coverage_gate(
    identity: Dict[str, Any],
    map_extent_wgs84: Dict[str, Any],
    *,
    margin_deg: float = 0.0,
) -> Dict[str, Any]:
    """Coverage verdict: DEM must fully cover the map WGS84 extent.

    Returns explicit metrics:
    - bbox_intersection_area_fraction: area(DEM ∩ Map) / area(Map)
    - sampled_map_points_inside_dem_fraction: requires sampled points (computed elsewhere)
    - nodata_fraction_at_samples: requires sampled points (computed elsewhere)
    """
    if not identity.get("ok", False):
        return {"ok": False, "reason": f"dem_identity:{identity.get('reason')}"}
    if map_extent_wgs84 is None:
        return {"ok": False, "reason": "map_extent_unavailable"}

    dem_b = identity.get("bounds_wgs84", {})
    if None in (dem_b.get("lon_min"), dem_b.get("lat_min"), dem_b.get("lon_max"), dem_b.get("lat_max")):
        return {
            "ok": False,
            "reason": "dem_bounds_wgs84_unavailable",
            "bbox_intersection_area_fraction": 0.0,
            "fully_covered": False,
        }

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

    # bbox_intersection_area_fraction
    intersection = _rect_intersection(dem_b, me)
    map_area = _rect_area_m2(me)
    inter_area = _rect_area_m2(intersection) if intersection else 0.0
    bbox_intersection_area_fraction = (inter_area / map_area) if map_area > 0 else 0.0

    return {
        "ok": bool(fully_covered),
        "fully_covered": bool(fully_covered),
        "dem_bounds_wgs84": dem_b,
        "map_extent_wgs84": me,
        "needed_bounds_wgs84": needed,
        "bbox_intersection_area_fraction": bbox_intersection_area_fraction,
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