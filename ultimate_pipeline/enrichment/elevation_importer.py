# ultimate_pipeline/enrichment/elevation_importer.py

import math
import hashlib
import os
import re
import shutil
import subprocess
import statistics
import xml.etree.ElementTree as ET
from ultimate_pipeline.core.georef_utils import parse_georeference, canonical_manual_georeference
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import rasterio
except ImportError:
    rasterio = None

try:
    from pyproj import CRS, Transformer
except ImportError:
    CRS = None
    Transformer = None

HEADER_OFFSET_GPS_ANCHOR_THRESHOLD_M = 2000.0


def _parse_utm_zone_from_georef(georef_text: Optional[str]) -> int:
    """
    Extract UTM zone from geoReference PROJ.4 string.
    Returns zone number or 32 as fallback (Ingolstadt default).

    Example: "+proj=utm +zone=32 +datum=WGS84 ..." -> 32
    """
    if not georef_text:
        return 32
    match = re.search(r"\+zone=(\d+)", georef_text)
    if match:
        return int(match.group(1))
    return 32


def _get_georef_from_xodr(xodr_path: str) -> Optional[str]:
    """Extract geoReference text from XODR file."""
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is not None:
            geo = header.find("geoReference")
            if geo is not None and geo.text:
                raw = (geo.text or "").strip()
                if not raw:
                    return None
                valid, params_complete, norm = parse_georeference(raw)
                return norm or raw
    except Exception:
        pass
    return None


def _canonical_tmerc_proj_from_settings() -> Optional[str]:
    """Canonical map CRS for comparability with the manual Ingolstadt map.

    We deliberately use the same PROJ.4 string as the manual/reference map:
    +proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs

    This prevents CRS promotion and keeps domain-gap analysis well-defined.
    """
    try:
        return canonical_manual_georeference()
    except Exception:
        # Last-resort fallback: keep the exact literal (already normalized).
        return "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"


def _utm_zone_from_lon(lon_deg: float) -> int:
    try:
        lon = float(lon_deg)
    except Exception:
        return 32
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    return max(1, min(60, zone))


def _canonical_utm_proj_from_settings() -> Optional[str]:
    """Best-effort canonical UTM CRS from configured GPS bounds."""
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        gps = getattr(SETTINGS, "GPS_BOUNDS", None) or SETTINGS.load_gps_bounds()
        lat_center = (float(gps["lat_min"]) + float(gps["lat_max"])) / 2.0
        lon_center = (float(gps["lon_min"]) + float(gps["lon_max"])) / 2.0
        zone = _utm_zone_from_lon(lon_center)
        hemi = "+south " if lat_center < 0.0 else ""
        proj4 = f"+proj=utm +zone={zone} {hemi}+datum=WGS84 +units=m +no_defs"
        return " ".join(proj4.split())
    except Exception:
        return None


def _complete_tmerc_georef(georef_text: Optional[str]) -> Optional[str]:
    if not georef_text:
        return None
    raw = " ".join(str(georef_text).split())
    if "+proj=tmerc" not in raw:
        return raw

    fallback = _canonical_tmerc_proj_from_settings()
    if not fallback:
        return raw

    completed = raw
    for token in (
        "+lat_0=",
        "+lon_0=",
        "+k=",
        "+x_0=",
        "+y_0=",
        "+datum=",
        "+units=",
        "+no_defs",
    ):
        if token in completed:
            continue
        if token == "+no_defs":
            completed = f"{completed} +no_defs"
            continue
        # Avoid f-string brace escaping / invalid escape sequences by escaping the token
        # for regex usage explicitly.
        m = re.search(rf"({re.escape(token)}\S+)", fallback)
        if m:
            completed = f"{completed} {m.group(1)}"
    return " ".join(completed.split())


def _strict_quality_gates_enabled() -> bool:
    from ultimate_pipeline.config.settings import SETTINGS

    return bool(getattr(SETTINGS, "DEM_STRICT_MODE", True))


def _get_map_crs_from_georef(georef_text: Optional[str]):
    if not georef_text or CRS is None:
        return None
    _, _, norm = parse_georeference(georef_text)
    georef_norm = norm or georef_text
    if "+proj=utm" in georef_norm or "+zone=" in georef_norm:
        zone = _parse_utm_zone_from_georef(georef_text)
        try:
            return CRS.from_proj4(
                f"+proj=utm +zone={zone} +datum=WGS84 +units=m +no_defs"
            )
        except Exception:
            pass
    candidates = [norm or georef_text]
    completed = _complete_tmerc_georef(georef_text)
    if completed and completed not in candidates:
        candidates.append(completed)

    for cand in candidates:
        try:
            return CRS.from_user_input(cand)
        except Exception:
            continue

    if "+proj=utm" in georef_norm or "+zone=" in georef_norm:
        zone = _parse_utm_zone_from_georef(georef_text)
        try:
            return CRS.from_proj4(
                f"+proj=utm +zone={zone} +datum=WGS84 +units=m +no_defs"
            )
        except Exception:
            return None
    return None


def _is_incomplete_tmerc(crs_obj: Any) -> bool:
    try:
        proj4 = str(crs_obj.to_proj4())
    except Exception:
        # Test doubles and lightweight CRS wrappers may not implement to_proj4().
        # Treat unknown formats as "not proven incomplete" to avoid false strict failures.
        return False
    proj4_norm = " ".join(proj4.split())
    if proj4_norm == "+proj=tmerc +type=crs":
        return True
    if "+proj=tmerc" not in proj4_norm:
        return False
    required = ["+lat_0=", "+lon_0=", "+k=", "+x_0=", "+y_0="]
    return any(token not in proj4_norm for token in required)


def _is_incomplete_tmerc_text(georef_text: Optional[str]) -> bool:
    if not georef_text:
        return False
    georef_norm = " ".join(str(georef_text).split())
    if "+proj=tmerc" not in georef_norm:
        return False
    if georef_norm.strip() == "+proj=tmerc +type=crs":
        return True
    required = ["+lat_0=", "+lon_0=", "+k=", "+x_0=", "+y_0="]
    return any(token not in georef_norm for token in required)


def _infer_map_crs(
    xodr_path: Optional[str], georef_text: Optional[str]
) -> Tuple[Any, str, str]:
    georef = georef_text
    if not georef and xodr_path:
        georef = _get_georef_from_xodr(xodr_path)

    def _forced_incomplete_tmerc_fallback() -> Tuple[Any, str, str]:
        # Option A (thesis / domain-gap correctness):
        # If the XODR has an incomplete tmerc, force the canonical manual CRS
        # rather than switching to UTM. Switching projections breaks manual/auto
        # comparability and can cause DEM sampling drift (floating roads).
        tmerc_fallback = _canonical_tmerc_proj_from_settings()
        if tmerc_fallback:
            forced_tmerc = _get_map_crs_from_georef(tmerc_fallback)
            if forced_tmerc is not None and not _is_incomplete_tmerc(forced_tmerc):
                print(
                    "[DEM] Incomplete tmerc detected; forcing canonical manual tmerc CRS "
                    "(lon_0=9, x_0=500000) for domain-gap comparability."
                )
                return (
                    forced_tmerc,
                    "manual_tmerc_forced",
                    tmerc_fallback,
                )
        return None, "unresolved", georef or ""

    if _is_incomplete_tmerc_text(georef):
        forced_crs, forced_source, forced_raw = _forced_incomplete_tmerc_fallback()
        if forced_crs is not None:
            return forced_crs, forced_source, forced_raw

    if georef:
        map_crs = _get_map_crs_from_georef(georef)
        if map_crs is not None:
            force_fallback = _is_incomplete_tmerc(map_crs)
            if not force_fallback:
                try:
                    proj4_norm = " ".join(str(map_crs.to_proj4()).split())
                except Exception:
                    proj4_norm = ""
                if proj4_norm.strip() == "+proj=tmerc +type=crs":
                    force_fallback = True
            if force_fallback:
                forced_crs, forced_source, forced_raw = (
                    _forced_incomplete_tmerc_fallback()
                )
                if forced_crs is not None:
                    return forced_crs, forced_source, forced_raw
            else:
                return map_crs, "xodr_geoReference", georef

    fallback = _canonical_tmerc_proj_from_settings()
    if fallback:
        map_crs = _get_map_crs_from_georef(fallback)
        if map_crs is not None and not _is_incomplete_tmerc(map_crs):
            return map_crs, "settings_gps_bounds_tmerc", fallback

    return None, "unresolved", georef or ""


def _default_header_offset() -> Dict[str, float]:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "hdg": 0.0}


def _read_header_offset(xodr_path: Optional[str]) -> Optional[Dict[str, float]]:
    if not xodr_path or not os.path.exists(xodr_path):
        return None
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return None
        off = header.find("offset")
        if off is None:
            return None
        out = _default_header_offset()
        for key in ("x", "y", "z", "hdg"):
            try:
                out[key] = float(off.get(key, out[key]))
            except Exception:
                out[key] = 0.0
        return out
    except Exception:
        return None


def _apply_header_offset(
    x: float, y: float, off: Optional[Dict[str, float]]
) -> Tuple[float, float]:
    if not off:
        return float(x), float(y)
    try:
        hdg = float(off.get("hdg", 0.0))
        ox = float(off.get("x", 0.0))
        oy = float(off.get("y", 0.0))
    except Exception:
        return float(x), float(y)
    cos_h = math.cos(hdg)
    sin_h = math.sin(hdg)
    # Project convention: rotate local planView point by header offset heading, then translate.
    xx = float(x) * cos_h - float(y) * sin_h + ox
    yy = float(x) * sin_h + float(y) * cos_h + oy
    return xx, yy


def _compute_xodr_planview_bbox(
    xodr_path: Optional[str],
    header_offset: Optional[Dict[str, float]] = None,
) -> Optional[Dict[str, float]]:
    if not xodr_path or not os.path.exists(xodr_path):
        return None
    off = header_offset if header_offset is not None else _read_header_offset(xodr_path)
    if off is None:
        off = _default_header_offset()
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        xs: List[float] = []
        ys: List[float] = []
        for geom in root.findall(".//road/planView/geometry"):
            x_raw = geom.get("x")
            y_raw = geom.get("y")
            if x_raw is None or y_raw is None:
                continue
            try:
                x_adj, y_adj = _apply_header_offset(float(x_raw), float(y_raw), off)
                xs.append(float(x_adj))
                ys.append(float(y_adj))
            except Exception:
                continue
        if not xs or not ys:
            return None
        return {
            "minx": float(min(xs)),
            "miny": float(min(ys)),
            "maxx": float(max(xs)),
            "maxy": float(max(ys)),
        }
    except Exception:
        return None


def _bbox_center(bbox: Optional[Dict[str, float]]) -> Optional[Tuple[float, float]]:
    if not isinstance(bbox, dict):
        return None
    try:
        cx = (float(bbox["minx"]) + float(bbox["maxx"])) * 0.5
        cy = (float(bbox["miny"]) + float(bbox["maxy"])) * 0.5
        return cx, cy
    except Exception:
        return None


def _gps_center_projected_in_map_crs(map_crs: Any) -> Optional[Tuple[float, float]]:
    if map_crs is None or CRS is None or Transformer is None:
        return None
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        gps = getattr(SETTINGS, "GPS_BOUNDS", None) or SETTINGS.load_gps_bounds()
        lat_center = (float(gps["lat_min"]) + float(gps["lat_max"])) * 0.5
        lon_center = (float(gps["lon_min"]) + float(gps["lon_max"])) * 0.5
        tf = Transformer.from_crs(
            CRS.from_user_input("EPSG:4326"), map_crs, always_xy=True
        )
        x_proj, y_proj = tf.transform(lon_center, lat_center)
        return float(x_proj), float(y_proj)
    except Exception:
        return None


def _offset_from_gps_anchor(
    local_bbox: Optional[Dict[str, float]],
    gps_center_xy: Optional[Tuple[float, float]],
    base_offset: Optional[Dict[str, float]],
) -> Optional[Dict[str, float]]:
    local_center = _bbox_center(local_bbox)
    if local_center is None or gps_center_xy is None:
        return None
    base = dict(base_offset or _default_header_offset())
    try:
        hdg = float(base.get("hdg", 0.0))
        z_val = float(base.get("z", 0.0))
    except Exception:
        hdg = 0.0
        z_val = 0.0
    cos_h = math.cos(hdg)
    sin_h = math.sin(hdg)
    lx = float(local_center[0])
    ly = float(local_center[1])
    rx = lx * cos_h - ly * sin_h
    ry = lx * sin_h + ly * cos_h
    return {
        "x": float(gps_center_xy[0] - rx),
        "y": float(gps_center_xy[1] - ry),
        "z": float(z_val),
        "hdg": float(hdg),
    }


def _bbox_to_wgs84(
    bbox: Optional[Dict[str, float]],
    src_crs: Any,
) -> Optional[Dict[str, float]]:
    if bbox is None or src_crs is None or CRS is None or Transformer is None:
        return None
    try:
        wgs84 = CRS.from_user_input("EPSG:4326")
        if src_crs == wgs84:
            return dict(bbox)
        tf = Transformer.from_crs(src_crs, wgs84, always_xy=True)
        return _transform_bbox(bbox, tf)
    except Exception:
        return None


def _transform_bbox(
    bbox: Dict[str, float], transformer: Any
) -> Optional[Dict[str, float]]:
    try:
        corners = (
            (float(bbox["minx"]), float(bbox["miny"])),
            (float(bbox["minx"]), float(bbox["maxy"])),
            (float(bbox["maxx"]), float(bbox["miny"])),
            (float(bbox["maxx"]), float(bbox["maxy"])),
        )
        tx: List[float] = []
        ty: List[float] = []
        for x, y in corners:
            xx, yy = transformer.transform(x, y)
            tx.append(float(xx))
            ty.append(float(yy))
        return {
            "minx": float(min(tx)),
            "miny": float(min(ty)),
            "maxx": float(max(tx)),
            "maxy": float(max(ty)),
        }
    except Exception:
        return None


def _bbox_intersects(a: Dict[str, float], b: Dict[str, float]) -> bool:
    return not (
        float(a["maxx"]) < float(b["minx"])
        or float(a["minx"]) > float(b["maxx"])
        or float(a["maxy"]) < float(b["miny"])
        or float(a["miny"]) > float(b["maxy"])
    )


def _normalize_bbox(bbox: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
    if not isinstance(bbox, dict):
        return None
    try:
        return {
            "minx": float(bbox["minx"]),
            "miny": float(bbox["miny"]),
            "maxx": float(bbox["maxx"]),
            "maxy": float(bbox["maxy"]),
        }
    except Exception:
        return None


def _compute_dem_overlap_diagnostics(
    xodr_path: Optional[str],
    map_crs: Any,
    dem_crs_obj: Any,
    dem_bounds_in_dem_crs: Optional[Dict[str, float]],
    header_offset: Optional[Dict[str, float]],
) -> Dict[str, Any]:
    map_bbox_in_map_crs = _compute_xodr_planview_bbox(
        xodr_path, header_offset=header_offset
    )
    projected_bbox_utm = _normalize_bbox(map_bbox_in_map_crs)
    map_bbox_transformed_to_dem_crs = None
    projected_bbox_wgs84 = _bbox_to_wgs84(projected_bbox_utm, map_crs)
    dem_bounds_wgs84 = _bbox_to_wgs84(dem_bounds_in_dem_crs, dem_crs_obj)
    bbox_intersects_dem_bounds_wgs84 = None
    bbox_intersects_dem_bounds = None

    if map_bbox_in_map_crs is not None and dem_bounds_in_dem_crs is not None:
        if dem_crs_obj is not None and map_crs is not None and Transformer is not None:
            if dem_crs_obj == map_crs:
                map_bbox_transformed_to_dem_crs = dict(map_bbox_in_map_crs)
            else:
                try:
                    bbox_tf = Transformer.from_crs(map_crs, dem_crs_obj, always_xy=True)
                    map_bbox_transformed_to_dem_crs = _transform_bbox(
                        map_bbox_in_map_crs, bbox_tf
                    )
                except Exception:
                    map_bbox_transformed_to_dem_crs = None
        if (
            map_bbox_transformed_to_dem_crs is not None
            and dem_bounds_in_dem_crs is not None
        ):
            try:
                bbox_intersects_dem_bounds = _bbox_intersects(
                    map_bbox_transformed_to_dem_crs, dem_bounds_in_dem_crs
                )
            except Exception:
                bbox_intersects_dem_bounds = None

    if projected_bbox_wgs84 is not None and dem_bounds_wgs84 is not None:
        try:
            bbox_intersects_dem_bounds_wgs84 = _bbox_intersects(
                projected_bbox_wgs84, dem_bounds_wgs84
            )
        except Exception:
            bbox_intersects_dem_bounds_wgs84 = None

    return {
        "map_bbox_in_map_crs": map_bbox_in_map_crs,
        "projected_bbox_utm": projected_bbox_utm,
        "map_bbox_transformed_to_dem_crs": map_bbox_transformed_to_dem_crs,
        "projected_bbox_wgs84": projected_bbox_wgs84,
        "dem_bounds_wgs84": dem_bounds_wgs84,
        "bbox_intersects_dem_bounds": bbox_intersects_dem_bounds,
        "bbox_intersects_dem_bounds_wgs84": bbox_intersects_dem_bounds_wgs84,
    }


def _unwrap_sampler_result(
    result: Union[Tuple[Optional[float], bool], float, int, None],
) -> Tuple[Optional[float], bool]:
    if result is None:
        return None, False
    if isinstance(result, tuple) and len(result) == 2:
        z_val, valid = result
        if z_val is None:
            return None, False
        try:
            return float(z_val), bool(valid)
        except Exception:
            return None, False
    try:
        z_val = float(result)
    except Exception:
        return None, False
    if not math.isfinite(z_val):
        return None, False
    return z_val, True


def summarize_dem_raster_stats(tif_path: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "dem_raster_min": None,
        "dem_raster_max": None,
        "dem_raster_range": None,
        "dem_raster_count": 0,
    }
    if rasterio is None:
        out["dem_raster_reason"] = "rasterio_unavailable"
        return out
    try:
        import numpy as np

        with rasterio.open(tif_path) as ds:
            band = ds.read(1).astype(float)
            nodata_val = ds.nodata
        mask = np.isfinite(band)
        if nodata_val is not None:
            mask &= np.abs(band - float(nodata_val)) > 1e-6
        mask &= band > -9998.0
        mask &= band < 9998.0
        vals = band[mask]
        if vals.size <= 0:
            out["dem_raster_reason"] = "no_valid_pixels"
            return out
        dem_min = float(np.min(vals))
        dem_max = float(np.max(vals))
        out.update(
            {
                "dem_raster_min": dem_min,
                "dem_raster_max": dem_max,
                "dem_raster_range": float(dem_max - dem_min),
                "dem_raster_count": int(vals.size),
            }
        )
        return out
    except Exception as exc:
        out["dem_raster_reason"] = f"read_failed:{exc}"
        return out


def build_dem_qc_report(
    *,
    sampled_points: int,
    nodata_points: int,
    sample_values: List[float],
    dem_present: bool,
    sampling_frame: str = "local",
    dem_raster_min: Optional[float] = None,
    dem_raster_max: Optional[float] = None,
    nodata_ratio_fail_threshold: float = 0.2,
    suspicious_raster_range_threshold: float = 0.5,
    flat_sample_range_threshold: float = 0.05,
) -> Dict[str, Any]:
    vals = [
        float(v)
        for v in sample_values
        if isinstance(v, (int, float)) and math.isfinite(float(v))
    ]
    sampled = int(max(0, sampled_points))
    nodata = int(max(0, nodata_points))
    ratio = float(nodata / sampled) if sampled > 0 else 0.0

    if vals:
        z_min = float(min(vals))
        z_max = float(max(vals))
        z_range = float(z_max - z_min)
        z_mean = float(sum(vals) / len(vals))
        z_std = float(math.sqrt(sum((v - z_mean) ** 2 for v in vals) / len(vals)))
    else:
        z_min = None
        z_max = None
        z_range = 0.0
        z_mean = None
        z_std = 0.0

    dem_range = None
    if dem_raster_min is not None and dem_raster_max is not None:
        try:
            dem_range = float(float(dem_raster_max) - float(dem_raster_min))
        except Exception:
            dem_range = None

    ok = True
    reason = ""
    if dem_present:
        if ratio > float(nodata_ratio_fail_threshold):
            ok = False
            reason = (
                f"dem_nodata_ratio_exceeds_threshold:"
                f"{ratio:.6f}>{float(nodata_ratio_fail_threshold):.6f}"
            )
        elif (
            dem_range is not None
            and float(dem_range) > float(suspicious_raster_range_threshold)
            and float(z_range) < float(flat_sample_range_threshold)
        ):
            ok = False
            reason = (
                "suspicious_flat_sampling:"
                f"dem_raster_range={float(dem_range):.6f}>"
                f"{float(suspicious_raster_range_threshold):.6f} "
                f"and sampled_z_range={float(z_range):.6f}<"
                f"{float(flat_sample_range_threshold):.6f}"
            )
    else:
        reason = "dem_not_present"

    return {
        "ok": bool(ok),
        "reason": str(reason),
        "sampled_points": int(sampled),
        "nodata_points": int(nodata),
        "dem_nodata_ratio": float(ratio),
        "sampling_frame": str(sampling_frame),
        "z_min": z_min,
        "z_max": z_max,
        "z_range": float(z_range),
        "z_mean": z_mean,
        "z_std": float(z_std),
        "dem_raster_min": dem_raster_min,
        "dem_raster_max": dem_raster_max,
        "dem_raster_range": dem_range,
        "nodata_ratio_fail_threshold": float(nodata_ratio_fail_threshold),
        "suspicious_raster_range_threshold": float(suspicious_raster_range_threshold),
        "flat_sample_range_threshold": float(flat_sample_range_threshold),
    }


class ElevationImporter:
    """
    Fills OpenDRIVE <elevation> records from a DEM.

    Strategy:
    - You provide a sampler: (x, y) -> z
    - For each <elevation> element: set a=z, b=c=d=0
    - If no <elevation> exists but DEM is present: create a single flat segment.
    """

    @staticmethod
    def apply_dem(
        root: ET.Element,
        sampler: Callable[[float, float], Union[Tuple[Optional[float], bool], float]],
        *,
        collect_qc: bool = False,
        linear_grade: Optional[bool] = None,
        structure_road_ids: Optional[set] = None,
    ) -> Optional[Dict[str, Any]]:
        from ultimate_pipeline.enrichment.elevation_fallback_policy import (
            elevation_fallback_policy,
            assert_no_fallback_violations,
        )
        f2_policy = elevation_fallback_policy()

        # thesis_strict is now driven solely by the F2 fallback policy
        settings_obj = None
        if f2_policy == "strict":
            thesis_strict = True
        elif f2_policy == "audit":
            thesis_strict = False
        else:
            thesis_strict = os.getenv("UP_THESIS_STRICT", "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            try:
                from ultimate_pipeline.config.settings import SETTINGS as _SETTINGS

                settings_obj = _SETTINGS
                thesis_strict = bool(getattr(_SETTINGS, "THESIS_STRICT", False)) or thesis_strict
            except Exception:
                settings_obj = None

        # Resolve linear_grade from settings if not explicitly provided
        if linear_grade is None:
            # Thesis strict: prefer endpoint-based linear grade to improve continuity at road joins.
            if thesis_strict:
                linear_grade = True
            elif settings_obj is not None:
                linear_grade = bool(getattr(settings_obj, "ELEVATION_LINEAR_GRADE", False))
            else:
                linear_grade = False

        # Max allowed |grade| (b coefficient) for a road elevation profile.
        # Endpoint-based linear grade (DEM) can produce physically implausible
        # near-vertical ramps when the DEM samples the two ends of a short road
        # at different vertical layers (overpass/underpass artifacts). Clamp on
        # generation so the checker's UP_ELEVATION_MAX_GRADE (default 0.2)
        # never sees a violation from this writer.
        try:
            max_grade = float(os.getenv("UP_ELEVATION_MAX_GRADE", "0.2"))
        except Exception:
            max_grade = 0.2

        sampled_points = 0
        nodata_points = 0
        sample_values: List[float] = []
        sampled_road_ids: List[str] = []
        nodata_road_ids: List[str] = []
        applied_road_ids: List[str] = []
        fallback_road_ids: List[str] = []
        linear_grade_road_ids: List[str] = []
        grade_clamped_road_ids: List[str] = []
        endpoint_nodata_road_ids: List[str] = []
        extrapolated_road_ids: List[str] = []
        propagated_road_ids: List[str] = []
        deferred_roads: List[Dict[str, Any]] = []
        valid_samples: List[Tuple[float, float, float]] = []
        applied_z_by_road: Dict[str, float] = {}
        fallback_active = bool(getattr(sampler, "_dem_fallback_active", False))

        def _set_flat_elevation(road_elem: ET.Element, z_value: float, b_coeff: float = 0.0) -> None:
            # Defensive grade clamp at the writer: no elevation segment may
            # exceed |max_grade| regardless of caller.
            if abs(b_coeff) > max_grade:
                b_coeff = max(-max_grade, min(max_grade, b_coeff))
            elev_elem = road_elem.find("elevationProfile")
            if elev_elem is None:
                elev_elem = ET.SubElement(road_elem, "elevationProfile")

            existing = list(elev_elem.findall("elevation"))
            for existing_elem in existing:
                elev_elem.remove(existing_elem)

            ET.SubElement(
                elev_elem,
                "elevation",
                {
                    "s": "0.0",
                    "a": f"{z_value:.3f}",
                    "b": f"{b_coeff:.6f}",
                    "c": "0.0",
                    "d": "0.0",
                },
            )

        for road in root.findall("road"):
            rid = str(road.get("id", "UNKNOWN"))
            road_forced_linear_grade = bool(structure_road_ids) and rid in structure_road_ids
            plan = road.find("planView")
            if plan is None:
                continue

            geos = plan.findall("geometry")
            if not geos:
                continue
            sampled_points += 1
            sampled_road_ids.append(rid)

            # take start of first geometry as anchor
            g0 = geos[0]
            try:
                x0 = float(g0.get("x", "0"))
                y0 = float(g0.get("y", "0"))
                hdg0 = float(g0.get("hdg", "0"))
            except Exception:
                x0, y0, hdg0 = 0.0, 0.0, 0.0

            # Robust start sampling: DEM rasters can be half-open at borders or contain nodata holes.
            # Try a small neighborhood before declaring nodata.
            def _try_sample(px, py):
                z, ok = _unwrap_sampler_result(sampler(px, py))
                return (z, ok) if (ok and z is not None) else (None, False)

            def _try_neighborhood(px, py, hdg, eps_m):
                cand = []
                cand.append((px, py))
                cand.append((px + eps_m * math.cos(hdg), py + eps_m * math.sin(hdg)))
                cand.append((px - eps_m * math.cos(hdg), py - eps_m * math.sin(hdg)))
                cand.append((px - eps_m * math.sin(hdg), py + eps_m * math.cos(hdg)))
                cand.append((px + eps_m * math.sin(hdg), py - eps_m * math.cos(hdg)))
                for cx, cy in cand:
                    z, ok = _try_sample(cx, cy)
                    if ok and z is not None:
                        return z, True, cand
                return None, False, cand

            try:
                eps0 = float(os.getenv("UP_ELEVATION_START_SAMPLE_EPS_M", "2.0"))
            except Exception:
                eps0 = 2.0

            z0, valid, start_cand = _try_neighborhood(x0, y0, hdg0, eps0)
            if not valid or z0 is None:
                nodata_points += 1
                nodata_road_ids.append(rid)
                deferred_roads.append(
                    {
                        "road": road,
                        "road_id": rid,
                        "x0": float(x0),
                        "y0": float(y0),
                        "hdg0": float(hdg0),
                        "eps0": float(eps0),
                        "start_candidates_tried": int(len(start_cand)),
                    }
                )
                continue
            sample_values.append(float(z0))
            valid_samples.append((float(x0), float(y0), float(z0)))

            # Compute linear grade if enabled (globally, or forced per-road for
            # bridge/tunnel/elevated/underpass structures via structure_road_ids):
            # sample road end to get slope.
            b_coeff = 0.0
            if linear_grade or road_forced_linear_grade:
                try:
                    road_length = float(road.get("length", "0"))
                except Exception:
                    road_length = 0.0
                if road_length > 0.01:  # avoid division by near-zero
                    # Compute endpoint using the last geometry only (stable and matches OpenDRIVE semantics):
                    # end ≈ (x_last, y_last) + length_last * heading_last
                    x_end, y_end = x0, y0
                    try:
                        gl = geos[-1]
                        geo_len = float(gl.get("length", "0"))
                        hdg = float(gl.get("hdg", "0"))
                        x_end = float(gl.get("x", x_end)) + geo_len * math.cos(hdg)
                        y_end = float(gl.get("y", y_end)) + geo_len * math.sin(hdg)
                    except Exception:
                        # keep fallback (x0,y0) -> slope stays 0
                        x_end, y_end = x0, y0
                    # Robust endpoint sampling: try a neighborhood near the road end.
                    def _try_sample(px, py):
                        z, ok = _unwrap_sampler_result(sampler(px, py))
                        return (z, ok) if (ok and z is not None) else (None, False)

                    def _try_neighborhood(px, py, hdg, eps_m):
                        cand = []
                        cand.append((px, py))
                        cand.append((px + eps_m * math.cos(hdg), py + eps_m * math.sin(hdg)))
                        cand.append((px - eps_m * math.cos(hdg), py - eps_m * math.sin(hdg)))
                        cand.append((px - eps_m * math.sin(hdg), py + eps_m * math.cos(hdg)))
                        cand.append((px + eps_m * math.sin(hdg), py - eps_m * math.cos(hdg)))
                        for cx, cy in cand:
                            z, ok = _try_sample(cx, cy)
                            if ok and z is not None:
                                return z, True
                        return None, False

                    try:
                        eps = float(os.getenv("UP_ELEVATION_END_SAMPLE_EPS_M", "2.0"))
                    except Exception:
                        eps = 2.0

                    z_end, valid_end = _try_neighborhood(x_end, y_end, hdg, eps)

                    if valid_end and z_end is not None:
                        b_coeff = (z_end - z0) / road_length
                        if abs(b_coeff) > max_grade:
                            b_coeff = max(-max_grade, min(max_grade, b_coeff))
                            grade_clamped_road_ids.append(rid)
                        linear_grade_road_ids.append(rid)
                    else:
                        # Record endpoint no-data violation; F2 gate will handle strict/audit behavior
                        endpoint_nodata_road_ids.append(rid)

            # In strict/audit mode, do not mutate the road if endpoint no-data occurred
            if rid in endpoint_nodata_road_ids and f2_policy in ("strict", "audit"):
                # Leave the original road elevation intact; do not apply flat elevation
                pass
            else:
                _set_flat_elevation(road, float(z0), b_coeff)
                applied_road_ids.append(rid)
                applied_z_by_road[rid] = float(z0)
                if fallback_active:
                    fallback_road_ids.append(rid)

        try:
            max_extrapolation_dist_m = float(
                os.getenv("UP_ELEV_EXTRAPOLATION_MAX_DIST_M", "2000.0")
            )
        except Exception:
            max_extrapolation_dist_m = 2000.0

        adjacency: Dict[str, List[str]] = {}
        for road_elem in root.findall("road"):
            road_id = str(road_elem.get("id", "UNKNOWN"))
            adjacency.setdefault(road_id, [])
            link = road_elem.find("link")
            if link is None:
                continue
            for direction in ("predecessor", "successor"):
                linked_elem = link.find(direction)
                if (
                    linked_elem is not None
                    and linked_elem.get("elementType") == "road"
                    and linked_elem.get("elementId")
                ):
                    neighbor_id = str(linked_elem.get("elementId"))
                    adjacency.setdefault(road_id, []).append(neighbor_id)
                    adjacency.setdefault(neighbor_id, []).append(road_id)

        remaining_deferred = list(deferred_roads)
        if deferred_roads and valid_samples:
            try:
                from scipy.spatial import cKDTree  # type: ignore
            except Exception:
                cKDTree = None
            if cKDTree is not None:
                tree = cKDTree([(x, y) for x, y, _ in valid_samples])
                remaining_deferred = []
                for deferred in deferred_roads:
                    rid = str(deferred["road_id"])
                    x0 = float(deferred["x0"])
                    y0 = float(deferred["y0"])
                    neighbor_count = min(5, len(valid_samples))
                    dists, idxs = tree.query([x0, y0], k=neighbor_count)
                    if isinstance(dists, (int, float)):
                        dist_list = [float(dists)]
                        idx_list = [int(idxs)]
                    else:
                        dist_list = [float(d) for d in dists]
                        idx_list = [int(i) for i in idxs]
                    valid_neighbors = [
                        (dist, idx)
                        for dist, idx in zip(dist_list, idx_list)
                        if math.isfinite(dist)
                    ]
                    if not valid_neighbors:
                        remaining_deferred.append(deferred)
                        continue
                    nearest_dist = min(dist for dist, _ in valid_neighbors)
                    if nearest_dist > float(max_extrapolation_dist_m):
                        remaining_deferred.append(deferred)
                        continue
                    # This road would be resolved via KD-tree nearest-neighbour extrapolation
                    extrapolated_road_ids.append(rid)
                    weights = [1.0 / (dist + 1.0e-6) for dist, _ in valid_neighbors]
                    z_fallback = sum(
                        weight * float(valid_samples[idx][2])
                        for weight, (_, idx) in zip(weights, valid_neighbors)
                    ) / sum(weights)
                    if f2_policy in ("strict", "audit"):
                        # Do NOT mutate the XML, do not update applied_z_by_road
                        pass
                    else:
                        _set_flat_elevation(deferred["road"], float(z_fallback), 0.0)
                        applied_road_ids.append(rid)
                        fallback_road_ids.append(rid)
                        applied_z_by_road[rid] = float(z_fallback)
            else:
                remaining_deferred = list(deferred_roads)

        unresolved_after_fallback: List[Dict[str, Any]] = []
        if remaining_deferred:
            unresolved_by_id = {str(item["road_id"]): item for item in remaining_deferred}
            for rid in sorted(unresolved_by_id):
                deferred = unresolved_by_id[rid]
                frontier: List[Tuple[str, int]] = [(rid, 0)]
                visited = {rid}
                resolved_z = None
                while frontier:
                    current, hops = frontier.pop(0)
                    if current != rid and current in applied_z_by_road:
                        resolved_z = float(applied_z_by_road[current])
                        break
                    if hops >= 5:
                        continue
                    for neighbor_id in adjacency.get(current, []):
                        if neighbor_id in visited:
                            continue
                        visited.add(neighbor_id)
                        frontier.append((neighbor_id, hops + 1))
                if resolved_z is not None:
                    # This road would be resolved via graph propagation
                    propagated_road_ids.append(rid)
                    if f2_policy in ("strict", "audit"):
                        # Do NOT mutate the XML, do not update applied_z_by_road
                        pass
                    else:
                        _set_flat_elevation(deferred["road"], float(resolved_z), 0.0)
                        applied_road_ids.append(rid)
                        fallback_road_ids.append(rid)
                        applied_z_by_road[rid] = float(resolved_z)
                else:
                    # This road would be resolved via global median or hardcoded fallback
                    unresolved_after_fallback.append(deferred)
                    if valid_samples:
                        resolved_z = float(statistics.median(sample[2] for sample in valid_samples))
                        print(
                            f"[ELEVATION][WARN] Road {rid} remained unresolved after DEM, KD-tree, and graph fallbacks. "
                            f"Would apply global median fallback z={resolved_z:.3f}m instead of leaving z=0."
                        )
                    else:
                        resolved_z = 375.0
                        print(
                            f"[ELEVATION][WARN] Road {rid} remained unresolved and no valid DEM samples existed. "
                            f"Would apply hardcoded Ingolstadt fallback z={resolved_z:.3f}m instead of leaving z=0."
                        )
                    if f2_policy in ("strict", "audit"):
                        # Do NOT mutate the XML
                        pass
                    else:
                        _set_flat_elevation(deferred["road"], float(resolved_z), 0.0)
                        applied_road_ids.append(rid)
                        fallback_road_ids.append(rid)
                        applied_z_by_road[rid] = float(resolved_z)

        # ------------------------------------------------------------
        # F2: strict fallback policy — any invented elevation value is a
        # hard failure (KD-tree NN extrapolation, graph propagation, global
        # median, hardcoded constant, or flat sampler).
        # ------------------------------------------------------------
        # f2_policy is already resolved at the top of the function
        f2_result = assert_no_fallback_violations(
            extrapolated_road_ids=extrapolated_road_ids,
            propagated_road_ids=propagated_road_ids,
            unresolved_road_ids=[
                str(item["road_id"]) for item in unresolved_after_fallback
            ],
            flat_sampler_active=bool(fallback_active),
            endpoint_nodata_road_ids=endpoint_nodata_road_ids,
            policy=f2_policy,
        )

        try:
            max_seam_delta_m = float(os.getenv("UP_ELEV_MAX_SEAM_DELTA_M", "30.0"))
        except Exception:
            max_seam_delta_m = 30.0

        suspect_seam_roads: List[Dict[str, Any]] = []
        seen_pairs = set()
        for road_id in sorted(adjacency):
            if road_id not in applied_z_by_road:
                continue
            for neighbor_id in sorted(set(adjacency.get(road_id, []))):
                if neighbor_id not in applied_z_by_road:
                    continue
                pair_key = tuple(sorted((road_id, neighbor_id)))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                delta_z = abs(float(applied_z_by_road[road_id]) - float(applied_z_by_road[neighbor_id]))
                if delta_z <= float(max_seam_delta_m):
                    continue
                suspect = {
                    "road_a": str(pair_key[0]),
                    "road_b": str(pair_key[1]),
                    "delta_z_m": float(delta_z),
                    "threshold_m": float(max_seam_delta_m),
                }
                suspect_seam_roads.append(suspect)
                print(
                    f"[ELEVATION][WARN] Elevation seam exceeds threshold between roads {pair_key[0]} and {pair_key[1]}: "
                    f"|dz|={delta_z:.3f}m > {float(max_seam_delta_m):.3f}m."
                )

        if f2_policy == "strict" and suspect_seam_roads:
            first_suspect = suspect_seam_roads[0]
            raise RuntimeError(
                "[ELEVATION][STRICT] Elevation seam exceeds threshold between roads "
                f"{first_suspect['road_a']} and {first_suspect['road_b']}: "
                f"|dz|={float(first_suspect['delta_z_m']):.3f}m > {float(first_suspect['threshold_m']):.3f}m."
            )

        if collect_qc:
            return {
                "sampled_points": int(sampled_points),
                "nodata_points": int(nodata_points),
                "sample_values": [float(v) for v in sample_values],
                "sampled_road_ids": sorted(set(sampled_road_ids)),
                "nodata_road_ids": sorted(set(nodata_road_ids)),
                "applied_road_ids": sorted(set(applied_road_ids)),
                "fallback_road_ids": sorted(set(fallback_road_ids)),
                "linear_grade_enabled": bool(linear_grade),
                "linear_grade_road_ids": sorted(set(linear_grade_road_ids)),
                "max_grade": float(max_grade),
                "grade_clamped_road_ids": sorted(set(grade_clamped_road_ids)),
                "grade_clamped_count": int(len(set(grade_clamped_road_ids))),
                "endpoint_nodata_road_ids": sorted(set(endpoint_nodata_road_ids)),
                "extrapolated_road_ids": sorted(set(extrapolated_road_ids)),
                "extrapolated_count": int(len(set(extrapolated_road_ids))),
                "extrapolation_max_dist_m": float(max_extrapolation_dist_m),
                "propagated_road_ids": sorted(set(propagated_road_ids)),
                "propagated_count": int(len(set(propagated_road_ids))),
                "unresolved_road_ids": sorted({str(item["road_id"]) for item in unresolved_after_fallback}),
                "unresolved_count": int(len({str(item["road_id"]) for item in unresolved_after_fallback})),
                "suspect_seam_roads": suspect_seam_roads,
                "suspect_seam_count": int(len(suspect_seam_roads)),
                "max_seam_delta_m": float(max((item["delta_z_m"] for item in suspect_seam_roads), default=0.0)),
                "seam_delta_threshold_m": float(max_seam_delta_m),
                "f2_fallback_policy": f2_policy,
                "f2_fallback_violations": f2_result.get("violations"),
                "f2_fallback_violation_count": int(f2_result.get("violation_count", 0)),
                "f2_fallback_gate_passed": f2_result.get("passed", True),
            }
        return None

    # ---------- DEM from GeoTIFF ----------

    @staticmethod
    def reproject_dem_to_map_crs(
        tif_path: str,
        *,
        xodr_path: Optional[str] = None,
        out_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "ok": False,
            "output_dem_path": "",
            "reason": "",
            "method": "",
            "map_crs": "",
            "source_dem_crs": "",
        }
        if rasterio is None or CRS is None:
            report["reason"] = "rasterio_or_pyproj_unavailable"
            return report

        map_crs, map_crs_source, _ = _infer_map_crs(xodr_path, None)
        if map_crs is None:
            report["reason"] = "map_crs_unresolved"
            return report
        report["map_crs"] = str(map_crs)
        report["map_crs_source"] = str(map_crs_source)

        try:
            with rasterio.open(tif_path) as src:
                src_crs = src.crs
                if src_crs is None:
                    report["reason"] = "dem_crs_missing"
                    return report
                src_crs_obj = CRS.from_user_input(src_crs)
                report["source_dem_crs"] = str(src_crs_obj)
                if src_crs_obj == map_crs:
                    report.update(
                        {
                            "ok": True,
                            "output_dem_path": str(tif_path),
                            "reason": "already_aligned",
                            "method": "none",
                        }
                    )
                    return report
        except Exception as exc:
            report["reason"] = f"open_dem_failed:{exc}"
            return report

        if out_path:
            dst_path = Path(out_path)
        else:
            try:
                epsg = map_crs.to_epsg()
            except Exception:
                epsg = None
            if epsg is not None:
                tag = f"epsg{int(epsg)}"
            else:
                digest = hashlib.sha256(str(map_crs).encode("utf-8")).hexdigest()[:8]
                tag = f"custom_{digest}"
            src_path = Path(tif_path)
            dst_path = src_path.with_name(f"{src_path.stem}__reproj_to_{tag}.tif")

        if dst_path.exists():
            report.update(
                {
                    "ok": True,
                    "output_dem_path": str(dst_path),
                    "reason": "cached_reprojection",
                    "method": "cache",
                }
            )
            return report

        gdalwarp = shutil.which("gdalwarp")
        if gdalwarp:
            try:
                cmd = [
                    gdalwarp,
                    "-overwrite",
                    "-r",
                    "bilinear",
                    "-t_srs",
                    str(map_crs),
                    str(tif_path),
                    str(dst_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                report.update(
                    {
                        "ok": True,
                        "output_dem_path": str(dst_path),
                        "reason": "reprojected",
                        "method": "gdalwarp",
                    }
                )
                return report
            except Exception as exc:
                report["gdalwarp_error"] = str(exc)

        try:
            from rasterio.warp import Resampling, calculate_default_transform, reproject

            with rasterio.open(tif_path) as src:
                transform, width, height = calculate_default_transform(
                    src.crs, map_crs, src.width, src.height, *src.bounds
                )
                kwargs = src.meta.copy()
                kwargs.update(
                    {
                        "crs": map_crs,
                        "transform": transform,
                        "width": width,
                        "height": height,
                    }
                )

                with rasterio.open(dst_path, "w", **kwargs) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rasterio.band(src, i),
                            destination=rasterio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=map_crs,
                            resampling=Resampling.bilinear,
                        )

            report.update(
                {
                    "ok": True,
                    "output_dem_path": str(dst_path),
                    "reason": "reprojected",
                    "method": "rasterio_warp",
                }
            )
            return report
        except Exception as exc:
            report["reason"] = f"reproject_failed:{exc}"
            return report

    @staticmethod
    def make_raster_sampler(
        tif_path: str,
        xodr_path: Optional[str] = None,
        utm_zone: Optional[int] = None,
    ):
        """
        Returns a callable (x, y) -> z using a GeoTIFF DEM.

        Handles CRS transformation automatically:
        - If DEM is in EPSG:4326 (lat/lon), transforms OpenDRIVE x/y (UTM) to lon/lat.
        - UTM zone is determined from XODR geoReference or defaults to zone 32 (Ingolstadt).

        Parameters
        ----------
        tif_path : str
            Path to the GeoTIFF DEM file.
        xodr_path : str, optional
            Path to XODR file to extract geoReference for UTM zone detection.
        utm_zone : int, optional
            Override UTM zone (if not provided, parsed from XODR or defaults to 32).
        """
        if rasterio is None:
            raise RuntimeError(
                "rasterio is not installed. `pip install rasterio` first."
            )

        import numpy as np

        from ultimate_pipeline.config.settings import (
            SETTINGS,
        )  # to use DEM smoothing toggles

        ds = rasterio.open(tif_path)
        band1 = ds.read(1).astype(float)

        # ------------------------------------------------------------
        # Detect DEM CRS and set up coordinate transformer if needed
        # ------------------------------------------------------------
        transformer = None
        sampling_frame = "local"
        dem_crs = ds.crs
        strict = bool(
            getattr(SETTINGS, "DEM_STRICT_MODE", _strict_quality_gates_enabled())
        )
        enable_transform = bool(getattr(SETTINGS, "ENABLE_DEM_CRS_TRANSFORM", True))
        header_offset_original = _read_header_offset(xodr_path) if xodr_path else None
        header_offset_source = (
            "xodr_header_offset"
            if header_offset_original is not None
            else "missing_default_zero"
        )
        if header_offset_original is None:
            header_offset_original = _default_header_offset()
        header_offset = dict(header_offset_original)
        header_offset_policy = "xodr_header"
        header_offset_error_m = None
        gps_anchor_offset_candidate = None
        local_raw_bbox = (
            _compute_xodr_planview_bbox(
                xodr_path, header_offset=_default_header_offset()
            )
            if xodr_path
            else None
        )

        dem_crs_obj = None
        georef = _get_georef_from_xodr(xodr_path) if xodr_path else None
        map_crs, map_crs_source, map_crs_raw = _infer_map_crs(xodr_path, georef)

        # ------------------------------------------------------------
        # F1: CRS contract — verify the geographic frame before sampling.
        # The pinned candidate's geoReference claims EPSG:32632 while the
        # geometry is in Osm2Odr's native tmerc(0,0) frame (WP1-verified,
        # 0.0 m).  Sampling with the claimed CRS alone would read the DEM at
        # the wrong geographic location.  resolve_sampling_crs decides the
        # true frame against the OSM source and fails closed when it cannot.
        # ------------------------------------------------------------
        f1_crs_contract = None
        if xodr_path:
            try:
                from ultimate_pipeline.dem.dem_crs_contract import (
                    resolve_sampling_crs,
                )

                _f1_osm = os.getenv("UP_OSM_FILE", "").strip()
                contract_crs, contract_source, contract_record = (
                    resolve_sampling_crs(
                        xodr_path, osm_path=_f1_osm or None, strict=strict
                    )
                )
            except Exception as exc:
                if strict:
                    raise RuntimeError(
                        f"[F1] DEM sampling CRS contract failed: {exc}"
                    ) from exc
                contract_crs, contract_source, contract_record = (
                    None,
                    "unverified",
                    None,
                )
            if contract_crs is not None and map_crs is not None and CRS is not None:
                map_crs = contract_crs
                map_crs_source = contract_source
            f1_crs_contract = contract_record
        gps_center_proj = _gps_center_projected_in_map_crs(map_crs)
        local_center = _bbox_center(local_raw_bbox)
        if local_center is not None and gps_center_proj is not None:
            gps_anchor_offset_candidate = _offset_from_gps_anchor(
                local_raw_bbox, gps_center_proj, header_offset_original
            )
            cx_header, cy_header = _apply_header_offset(
                float(local_center[0]),
                float(local_center[1]),
                header_offset_original,
            )
            header_offset_error_m = float(
                math.hypot(
                    float(cx_header) - float(gps_center_proj[0]),
                    float(cy_header) - float(gps_center_proj[1]),
                )
            )
            should_override = float(header_offset_error_m) > float(
                HEADER_OFFSET_GPS_ANCHOR_THRESHOLD_M
            )
            if should_override:
                # Check if user requested GPS-anchor override (Option B) via env var.
                # This is needed when: (1) UP_PREANCHOR_INPUT_XODR=1 was used but stages
                # normalized geometry to local frame without updating header offset, or
                # (2) the map has incorrect/inconsistent header offset.
                use_gps_anchor_offset = os.getenv(
                    "UP_USE_GPS_ANCHOR_OFFSET", ""
                ).strip().lower() in ("1", "true", "yes", "on")
                preanchor_active = os.getenv(
                    "UP_PREANCHOR_INPUT_XODR", ""
                ).strip().lower() in ("1", "true", "yes", "on")

                if use_gps_anchor_offset or preanchor_active:
                    # Option B: Use GPS-anchor-based offset for correct DEM sampling.
                    # This re-anchors the map but ensures DEM sampling works correctly.
                    gps_anchor_offset = gps_anchor_offset_candidate
                    if gps_anchor_offset:
                        header_offset = dict(gps_anchor_offset)
                        header_offset_policy = "gps_anchor_override"
                        print(
                            "[DEM] Header offset differs from GPS anchor by "
                            f"{float(header_offset_error_m):.3f}m > "
                            f"{float(HEADER_OFFSET_GPS_ANCHOR_THRESHOLD_M):.1f}m; "
                            "using GPS-anchored offset (Option B)."
                        )
                        print(f"[DEM] New offset: {header_offset}")
                    else:
                        header_offset_policy = "xodr_header_preserved"
                        print(
                            "[DEM] Header offset differs from GPS anchor by "
                            f"{float(header_offset_error_m):.3f}m; "
                            "GPS anchor offset unavailable, preserving original."
                        )
                else:
                    # Option A (thesis / domain-gap correctness):
                    # Preserve the original <header><offset>. Overriding the header offset
                    # re-anchors the map and breaks CRS/frame consistency with the manual map.
                    header_offset_policy = "xodr_header_preserved"
                    print(
                        "[DEM] Header offset differs from GPS anchor by "
                        f"{float(header_offset_error_m):.3f}m > "
                        f"{float(HEADER_OFFSET_GPS_ANCHOR_THRESHOLD_M):.1f}m; "
                        "preserving original header offset (Option A)."
                    )

        if CRS is not None and Transformer is not None:
            if dem_crs is not None:
                try:
                    dem_crs_obj = CRS.from_user_input(dem_crs)
                except Exception as e:
                    msg = f"[DEM] Failed to parse DEM CRS: {e}"
                    if strict:
                        raise RuntimeError(msg)
                    print(msg)
            if dem_crs_obj is not None and map_crs is not None:
                if dem_crs_obj != map_crs:
                    if not enable_transform:
                        msg = "[DEM] CRS mismatch detected but transform is disabled by settings.ENABLE_DEM_CRS_TRANSFORM."
                        if strict:
                            raise RuntimeError(msg)
                        print(msg)
                    else:
                        try:
                            transformer = Transformer.from_crs(
                                map_crs, dem_crs_obj, always_xy=True
                            )
                            sampling_frame = "projected"
                            print(
                                "[DEM] CRS mismatch detected; applying coordinate transform for sampling."
                            )
                        except Exception as e:
                            msg = f"[DEM] CRS transform setup failed: {e}"
                            if strict:
                                raise RuntimeError(msg)
                            print(msg)
                else:
                    sampling_frame = "projected"
            elif dem_crs_obj is not None and map_crs is None:
                msg = "[DEM] Map CRS not found in geoReference; cannot verify CRS alignment."
                if strict:
                    raise RuntimeError(msg)
                print(msg)
        else:
            if dem_crs is not None:
                msg = "[DEM] pyproj not available; cannot validate CRS alignment."
                if strict:
                    raise RuntimeError(msg)
                print(msg)

        # ------------------------------------------------------------
        # DEM smoothing to avoid steep, unnatural slopes in CARLA
        # ------------------------------------------------------------
        band1_smooth = band1
        if getattr(SETTINGS, "ENABLE_DEM_SMOOTHING", True):
            try:
                from scipy.ndimage import gaussian_filter

                sigma = getattr(SETTINGS, "DEM_SMOOTHING_SIGMA", 1.0)
                print(f"[DEM] Smoothing using Gaussian filter (sigma={sigma})...")
                band1_smooth = gaussian_filter(band1, sigma=sigma)
            except Exception as e:
                print(f"[DEM] Smoothing skipped (SciPy missing or error: {e})")
                band1_smooth = band1

        # Get nodata value from raster
        nodata_val = ds.nodata

        dem_bounds_in_dem_crs = None
        try:
            b = ds.bounds
            dem_bounds_in_dem_crs = {
                "minx": float(b.left),
                "miny": float(b.bottom),
                "maxx": float(b.right),
                "maxy": float(b.top),
            }
        except Exception:
            dem_bounds_in_dem_crs = None

        bbox_diag = _compute_dem_overlap_diagnostics(
            xodr_path=xodr_path,
            map_crs=map_crs,
            dem_crs_obj=dem_crs_obj,
            dem_bounds_in_dem_crs=dem_bounds_in_dem_crs,
            header_offset=header_offset,
        )
        gps_anchor_bbox_diag = None
        if (
            gps_anchor_offset_candidate is not None
            and header_offset_policy in ("xodr_header", "xodr_header_preserved")
            and (
                map_crs_source == "manual_tmerc_forced"
                or _is_incomplete_tmerc_text(georef)
            )
        ):
            gps_anchor_bbox_diag = _compute_dem_overlap_diagnostics(
                xodr_path=xodr_path,
                map_crs=map_crs,
                dem_crs_obj=dem_crs_obj,
                dem_bounds_in_dem_crs=dem_bounds_in_dem_crs,
                header_offset=gps_anchor_offset_candidate,
            )
            orig_overlap = (
                bbox_diag.get("bbox_intersects_dem_bounds") is True
                or bbox_diag.get("bbox_intersects_dem_bounds_wgs84") is True
            )
            gps_overlap = (
                gps_anchor_bbox_diag.get("bbox_intersects_dem_bounds") is True
                or gps_anchor_bbox_diag.get("bbox_intersects_dem_bounds_wgs84") is True
            )
            if not orig_overlap and gps_overlap:
                header_offset = dict(gps_anchor_offset_candidate)
                header_offset_policy = "gps_anchor_auto_repair"
                bbox_diag = gps_anchor_bbox_diag
                print(
                    "[DEM] Original header offset does not overlap DEM bounds in the "
                    "effective sampling frame, but the GPS-anchored candidate does; "
                    "auto-applying GPS-anchored offset."
                )
                print(f"[DEM] Auto-repaired offset: {header_offset}")

        map_bbox_in_map_crs = bbox_diag.get("map_bbox_in_map_crs")
        projected_bbox_utm = bbox_diag.get("projected_bbox_utm")
        map_bbox_transformed_to_dem_crs = bbox_diag.get("map_bbox_transformed_to_dem_crs")
        projected_bbox_wgs84 = bbox_diag.get("projected_bbox_wgs84")
        dem_bounds_wgs84 = bbox_diag.get("dem_bounds_wgs84")
        bbox_intersects_dem_bounds = bbox_diag.get("bbox_intersects_dem_bounds")
        bbox_intersects_dem_bounds_wgs84 = bbox_diag.get(
            "bbox_intersects_dem_bounds_wgs84"
        )

        likely_cause = ""
        if (
            bbox_intersects_dem_bounds is False
            or bbox_intersects_dem_bounds_wgs84 is False
        ):
            likely_cause = "CRS_or_georef_mismatch"

        print(f"[DEM] local_raw_bbox={local_raw_bbox}")
        print(f"[DEM] header_offset_original={header_offset_original}")
        print(f"[DEM] effective_offset_used={header_offset}")
        print(f"[DEM] projected_bbox_utm={projected_bbox_utm}")
        print(f"[DEM] projected_bbox_wgs84={projected_bbox_wgs84}")
        print(f"[DEM] dem_bounds_wgs84={dem_bounds_wgs84}")
        print(
            "[DEM] projected_bbox_wgs84_overlaps_dem_bounds="
            f"{bbox_intersects_dem_bounds_wgs84}"
        )

        if (
            strict
            and (
                bbox_intersects_dem_bounds is False
                or bbox_intersects_dem_bounds_wgs84 is False
            )
        ):
            gps_hint = ""
            if gps_anchor_bbox_diag is not None:
                gps_hint = (
                    f" gps_anchor_candidate_overlap_wgs84="
                    f"{gps_anchor_bbox_diag.get('bbox_intersects_dem_bounds_wgs84')}."
                )
            raise RuntimeError(
                "[DEM] Preflight overlap check failed before sampling: effective map bbox "
                f"{projected_bbox_wgs84} does not overlap DEM bounds {dem_bounds_wgs84}. "
                f"map_crs_source={map_crs_source}, header_offset_policy={header_offset_policy}, "
                f"header_offset_error_m={header_offset_error_m}.{gps_hint}"
            )

        sampling_error_counts = {
            "transform_error_points": 0,
            "raster_index_error_points": 0,
            "out_of_bounds_points": 0,
            "real_nodata_points": 0,
        }

        def sampler(x: float, y: float) -> Tuple[Optional[float], bool]:
            # Apply XODR header offset in map frame before any CRS transform.
            sample_x, sample_y = _apply_header_offset(float(x), float(y), header_offset)
            # Transform coordinates if DEM is in lat/lon or other CRS
            if transformer is not None:
                try:
                    sample_x, sample_y = transformer.transform(sample_x, sample_y)
                except Exception:
                    sampling_error_counts["transform_error_points"] += 1
                    return None, False

            # Sample from raster
            try:
                row, col = ds.index(sample_x, sample_y)
            except Exception:
                sampling_error_counts["raster_index_error_points"] += 1
                return None, False

            if (
                row < 0
                or col < 0
                or row >= band1_smooth.shape[0]
                or col >= band1_smooth.shape[1]
            ):
                sampling_error_counts["out_of_bounds_points"] += 1
                return None, False
            try:
                val = float(band1_smooth[row, col])
                # Check for nodata values
                if nodata_val is not None and abs(val - nodata_val) < 1e-6:
                    sampling_error_counts["real_nodata_points"] += 1
                    return None, False
                # Check for common nodata sentinel values
                if val <= -9998.0 or val >= 9998.0 or np.isnan(val):
                    sampling_error_counts["real_nodata_points"] += 1
                    return None, False
                return val, True
            except Exception:
                sampling_error_counts["raster_index_error_points"] += 1
                return None, False

        # Expose sampler metadata for QC artifact writing.
        try:
            setattr(sampler, "_sampling_frame", str(sampling_frame))
            setattr(sampler, "_crs_transform_applied", bool(transformer is not None))
            setattr(
                sampler,
                "_crs_mismatch_detected",
                bool(
                    dem_crs_obj is not None
                    and map_crs is not None
                    and dem_crs_obj != map_crs
                ),
            )
            setattr(sampler, "_map_crs", str(map_crs) if map_crs is not None else "")
            setattr(
                sampler,
                "_dem_crs",
                str(dem_crs_obj)
                if dem_crs_obj is not None
                else (str(dem_crs) if dem_crs is not None else ""),
            )
            setattr(sampler, "_header_offset", dict(header_offset))
            setattr(sampler, "_header_offset_original", dict(header_offset_original))
            setattr(sampler, "_effective_offset_used", dict(header_offset))
            setattr(sampler, "_header_offset_error_m", header_offset_error_m)
            setattr(sampler, "_header_offset_policy", str(header_offset_policy))
            setattr(sampler, "_header_offset_source", str(header_offset_source))
            setattr(sampler, "_gps_anchor_offset_candidate", gps_anchor_offset_candidate)
            setattr(sampler, "_sampling_error_counts", sampling_error_counts)
            setattr(sampler, "_map_crs_source", str(map_crs_source))
            setattr(sampler, "_map_crs_raw", str(map_crs_raw))
            setattr(sampler, "_local_raw_bbox", local_raw_bbox)
            setattr(sampler, "_projected_bbox_utm", projected_bbox_utm)
            setattr(sampler, "_projected_bbox_wgs84", projected_bbox_wgs84)
            setattr(sampler, "_dem_bounds_wgs84", dem_bounds_wgs84)
            setattr(sampler, "_map_bbox_in_map_crs", map_bbox_in_map_crs)
            setattr(
                sampler,
                "_map_bbox_transformed_to_dem_crs",
                map_bbox_transformed_to_dem_crs,
            )
            setattr(sampler, "_dem_bounds_in_dem_crs", dem_bounds_in_dem_crs)
            setattr(sampler, "_bbox_intersects_dem_bounds", bbox_intersects_dem_bounds)
            setattr(
                sampler,
                "_bbox_intersects_dem_bounds_wgs84",
                bbox_intersects_dem_bounds_wgs84,
            )
            setattr(sampler, "_gps_anchor_bbox_diag", gps_anchor_bbox_diag)
            setattr(sampler, "_likely_cause", likely_cause)
            setattr(sampler, "_f1_crs_contract", f1_crs_contract)
        except Exception:
            pass

        return sampler
