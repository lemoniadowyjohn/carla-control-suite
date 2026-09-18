# ultimate_pipeline/quality/check_dem_coverage.py
# -*- coding: utf-8 -*-

"""
DEM coverage check for OpenDRIVE elevation import.

Why:
- DEM files may not cover the full map extent (nodata or out-of-bounds).
- Silently sampling nodata causes flat elevation at 0.0 which creates unrealistic terrain.
- This gate detects when too many sample points return nodata/out-of-bounds.

What it checks:
- Samples N points along road reference lines.
- Counts valid samples (within DEM bounds and not nodata).
- Fails if valid_ratio < threshold (e.g., 0.6 = 60% coverage).

Outputs:
- A dict report suitable for JSON writing.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

# Sentinel for nodata values
NODATA_SENTINEL = -9999.0


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def _get_road_sample_points(
    root: ET.Element,
    max_roads: int = 50,
    samples_per_road: int = 3,
) -> List[Tuple[float, float, str]]:
    """
    Extract sample points (x, y, road_id) from road geometries.

    Samples points at start, middle, and end of each road's planView geometry.
    """
    points: List[Tuple[float, float, str]] = []
    roads = root.findall("road")

    # Deterministic sampling: pick evenly spaced roads
    step = max(1, len(roads) // max_roads)
    selected_roads = roads[::step][:max_roads]

    for road in selected_roads:
        rid = (road.get("id") or "").strip()
        road_len = _safe_float(road.get("length"))

        plan_view = road.find("planView")
        if plan_view is None:
            continue

        geometries = plan_view.findall("geometry")
        if not geometries:
            continue

        # Get first geometry start point
        g0 = geometries[0]
        x0 = _safe_float(g0.get("x"))
        y0 = _safe_float(g0.get("y"))
        hdg0 = _safe_float(g0.get("hdg"))

        # Sample at start
        points.append((x0, y0, rid))

        # Sample at approximate middle (simplified: use first geometry direction)
        if road_len > 0 and samples_per_road >= 2:
            mid_s = road_len / 2.0
            xm = x0 + math.cos(hdg0) * mid_s
            ym = y0 + math.sin(hdg0) * mid_s
            points.append((xm, ym, rid))

        # Sample at approximate end
        if road_len > 0 and samples_per_road >= 3:
            xe = x0 + math.cos(hdg0) * road_len
            ye = y0 + math.sin(hdg0) * road_len
            points.append((xe, ye, rid))

    return points


def _extract_georeference_from_header(root: ET.Element) -> Optional[str]:
    """Return OpenDRIVE header geoReference text if present and non-empty."""
    header = root.find("header")
    if header is None:
        return None
    geo = header.find("geoReference")
    if geo is None or not geo.text:
        return None
    text = str(geo.text).strip()
    return text or None


def check_dem_coverage(
    xodr_path: str,
    dem_path: str,
    threshold: float = 0.6,
    max_roads: int = 50,
    samples_per_road: int = 3,
    utm_zone: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Check DEM coverage for an OpenDRIVE map.

    Parameters
    ----------
    xodr_path : str
        Path to the OpenDRIVE file.
    dem_path : str
        Path to the DEM GeoTIFF file.
    threshold : float
        Minimum required ratio of valid samples (0.0 to 1.0).
    max_roads : int
        Maximum number of roads to sample from.
    samples_per_road : int
        Number of sample points per road.
    utm_zone : int, optional
        Override UTM zone for coordinate transformation.

    Returns
    -------
    dict
        {
            "ok": bool,
            "threshold": float,
            "total_samples": int,
            "valid_samples": int,
            "nodata_samples": int,
            "out_of_bounds_samples": int,
            "valid_ratio": float,
            "dem_path": str,
            "dem_crs": str,
            "dem_bounds": list,
            "sample_stats": {...},
            "warnings": [str]
        }
    """
    report: Dict[str, Any] = {
        "ok": True,
        "reason": "",
        "threshold": threshold,
        "total_samples": 0,
        "valid_samples": 0,
        "nodata_samples": 0,
        "out_of_bounds_samples": 0,
        "invalid_samples": 0,
        "valid_ratio": 1.0,
        "dem_path": dem_path,
        "dem_crs": None,
        "dem_bounds": None,
        "crs_conversion_applied": False,
        "xodr_proj": None,
        "sample_stats": {},
        "warnings": [],
    }

    # Parse XODR and read geoReference for CRS conversion.
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["reason"] = "xodr_parse_failed"
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    xodr_proj = _extract_georeference_from_header(root)
    report["xodr_proj"] = xodr_proj

    # Try to open DEM with rasterio
    try:
        import numpy as np
        import rasterio
    except ImportError:
        report["warnings"].append("rasterio not installed - DEM coverage check skipped")
        return report

    try:
        from pyproj import CRS, Transformer
    except Exception:
        CRS = None
        Transformer = None

    # Build CRS transformers:
    # XODR local/projected -> WGS84, and optionally WGS84 -> DEM CRS.
    xodr_to_wgs84 = None
    wgs84_to_dem = None
    missing_georef = False
    if not xodr_proj:
        missing_georef = True
        report["warnings"].append("missing <geoReference> in XODR header")
    elif CRS is None or Transformer is None:
        report["warnings"].append("pyproj not installed - CRS conversion unavailable")
    else:
        try:
            xodr_crs = CRS.from_proj4(xodr_proj)
            wgs84 = CRS.from_epsg(4326)
            xodr_to_wgs84 = Transformer.from_crs(xodr_crs, wgs84, always_xy=True)
            report["crs_conversion_applied"] = True
        except Exception as e:
            missing_georef = True
            report["warnings"].append(
                f"unparseable <geoReference> PROJ string; fallback to raw XODR XY sampling: {e}"
            )

    # Get sample points once from the parsed tree.
    points = _get_road_sample_points(
        root, max_roads=max_roads, samples_per_road=samples_per_road
    )
    report["total_samples"] = len(points)
    if not points:
        report["ok"] = False
        report["reason"] = "no_sample_points"
        report["valid_ratio"] = 0.0
        report["warnings"].append("no sample points extracted from XODR")
        return report

    try:
        with rasterio.open(dem_path) as ds:
            report["dem_crs"] = str(ds.crs) if ds.crs else None
            report["dem_bounds"] = list(ds.bounds) if ds.bounds else None
            nodata = ds.nodata
            band1 = ds.read(1)

            if (
                report["crs_conversion_applied"]
                and ds.crs is not None
                and CRS is not None
                and Transformer is not None
            ):
                try:
                    dem_crs_obj = CRS.from_user_input(ds.crs)
                    wgs84 = CRS.from_epsg(4326)
                    if dem_crs_obj != wgs84:
                        wgs84_to_dem = Transformer.from_crs(
                            wgs84, dem_crs_obj, always_xy=True
                        )
                except Exception as e:
                    report["warnings"].append(
                        f"failed to build WGS84->DEM transformer, using WGS84 coordinates directly: {e}"
                    )
                    wgs84_to_dem = None

            elevations: List[float] = []
            for x, y, _rid in points:
                sx = float(x)
                sy = float(y)

                if xodr_to_wgs84 is not None:
                    try:
                        lon, lat = xodr_to_wgs84.transform(sx, sy)
                        sx, sy = float(lon), float(lat)
                        if wgs84_to_dem is not None:
                            sx, sy = wgs84_to_dem.transform(sx, sy)
                    except Exception:
                        report["out_of_bounds_samples"] += 1
                        continue

                try:
                    row, col = ds.index(sx, sy)
                except Exception:
                    report["out_of_bounds_samples"] += 1
                    continue

                if (
                    row < 0
                    or col < 0
                    or row >= band1.shape[0]
                    or col >= band1.shape[1]
                ):
                    report["out_of_bounds_samples"] += 1
                    continue

                try:
                    z_val = float(band1[row, col])
                except Exception:
                    report["nodata_samples"] += 1
                    continue

                if not np.isfinite(z_val):
                    report["nodata_samples"] += 1
                    continue
                if nodata is not None and abs(z_val - float(nodata)) < 1e-6:
                    report["nodata_samples"] += 1
                    continue
                if z_val <= -9998.0 or z_val >= 9998.0:
                    report["nodata_samples"] += 1
                    continue

                report["valid_samples"] += 1
                elevations.append(z_val)
    except Exception as e:
        report["ok"] = False
        report["reason"] = "dem_open_or_sample_failed"
        report["warnings"].append(f"failed to open/sample DEM: {e}")
        return report

    report["invalid_samples"] = int(
        report["nodata_samples"] + report["out_of_bounds_samples"]
    )
    total = int(report["total_samples"])
    report["valid_ratio"] = (float(report["valid_samples"]) / float(total)) if total > 0 else 0.0

    if report["valid_samples"] > 0:
        # Keep JSON output stable with Python floats.
        report["sample_stats"] = {
            "min_z": float(min(elevations)),
            "max_z": float(max(elevations)),
            "mean_z": float(sum(elevations) / len(elevations)),
        }

    if missing_georef:
        # Required behavior: fallback sampling is allowed, but the gate must be reported
        # as failed with an explicit reason when geoReference is missing/unparseable.
        report["ok"] = False
        report["reason"] = "no_georeference"
    else:
        report["ok"] = report["valid_ratio"] >= threshold
        if not report["ok"]:
            report["reason"] = "coverage_below_threshold"
            report["warnings"].append(
                f"DEM coverage {report['valid_ratio']:.1%} is below threshold {threshold:.1%}"
            )

    return report


def check_dem_coverage_with_sampler(
    xodr_path: str,
    sampler: Callable[[float, float], Tuple[Optional[float], bool]],
    threshold: float = 0.6,
    max_roads: int = 50,
    samples_per_road: int = 3,
) -> Dict[str, Any]:
    """
    Check DEM coverage using an existing sampler function.

    The sampler should return (z_value, is_valid) tuple where is_valid=False
    indicates nodata or out-of-bounds.

    This variant is useful when you already have a configured sampler with
    proper CRS transformation.
    """
    report: Dict[str, Any] = {
        "ok": True,
        "threshold": threshold,
        "total_samples": 0,
        "valid_samples": 0,
        "invalid_samples": 0,
        "valid_ratio": 1.0,
        "sample_stats": {},
        "warnings": [],
    }

    # Parse XODR
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    # Get sample points
    points = _get_road_sample_points(root, max_roads=max_roads, samples_per_road=samples_per_road)
    report["total_samples"] = len(points)

    if not points:
        report["warnings"].append("no sample points extracted from XODR")
        return report

    # Sample at each point
    valid_count = 0
    invalid_count = 0
    elevations: List[float] = []

    for x, y, rid in points:
        try:
            result = sampler(x, y)
            if isinstance(result, tuple) and len(result) == 2:
                z_val, is_valid = result
            else:
                # Legacy sampler returns just z
                z_val = float(result)
                is_valid = z_val != 0.0 and z_val > -9998.0

            if is_valid and z_val is not None:
                valid_count += 1
                elevations.append(z_val)
            else:
                invalid_count += 1
        except Exception:
            invalid_count += 1

    report["valid_samples"] = valid_count
    report["invalid_samples"] = invalid_count

    total = report["total_samples"]
    if total > 0:
        report["valid_ratio"] = valid_count / total
    else:
        report["valid_ratio"] = 0.0

    if elevations:
        report["sample_stats"] = {
            "min_z": min(elevations),
            "max_z": max(elevations),
            "mean_z": sum(elevations) / len(elevations),
        }

    report["ok"] = report["valid_ratio"] >= threshold

    if not report["ok"]:
        report["warnings"].append(
            f"DEM coverage {report['valid_ratio']:.1%} is below threshold {threshold:.1%}"
        )

    return report


def run_check(
    *,
    xodr_path: str,
    dem_path: str,
    threshold: float = 0.6,
    max_roads: int = 50,
    samples_per_road: int = 3,
    utm_zone: Optional[int] = None,
) -> Dict[str, Any]:
    """Compatibility wrapper used by diagnostics/scripts."""
    return check_dem_coverage(
        xodr_path=str(xodr_path),
        dem_path=str(dem_path),
        threshold=threshold,
        max_roads=max_roads,
        samples_per_road=samples_per_road,
        utm_zone=utm_zone,
    )


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Check DEM coverage for OpenDRIVE map")
    ap.add_argument("xodr_path", help="Path to OpenDRIVE file")
    ap.add_argument("dem_path", help="Path to DEM GeoTIFF file")
    ap.add_argument("--threshold", type=float, default=0.6, help="Minimum valid ratio (0.0-1.0)")
    ap.add_argument("--max-roads", type=int, default=50)
    ap.add_argument("--samples-per-road", type=int, default=3)
    args = ap.parse_args()

    rep = check_dem_coverage(
        args.xodr_path,
        args.dem_path,
        threshold=args.threshold,
        max_roads=args.max_roads,
        samples_per_road=args.samples_per_road,
    )
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
