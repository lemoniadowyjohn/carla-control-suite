# ultimate_pipeline/domain_gap/tile_matcher.py
from __future__ import annotations

import glob
import json
import logging
import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import box

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.georef_utils import canonical_manual_georeference, parse_georeference

logger = logging.getLogger(__name__)

_WGS84_CRS = "EPSG:4326"
_COMMON_TILE_CRS = canonical_manual_georeference()


def _safe_float(val: str | None, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except Exception:
        return default


def _tile_index(name: str) -> Tuple[int, int]:
    match = re.search(r"tile_(\d+)_(\d+)\.xodr$", name)
    if not match:
        return (10**9, 10**9)
    return int(match.group(1)), int(match.group(2))


def _extract_bounds_from_tile_metadata_payload(
    data: Dict[str, Any],
) -> Dict[str, Tuple[float, float, float, float]]:
    out: Dict[str, Tuple[float, float, float, float]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or key.startswith("_") or not isinstance(value, dict):
            continue

        bounds = value.get("bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            try:
                out[key] = (
                    float(bounds[0]),
                    float(bounds[1]),
                    float(bounds[2]),
                    float(bounds[3]),
                )
                continue
            except Exception:
                pass

        bbox = value.get("bbox")
        if isinstance(bbox, dict):
            try:
                out[key] = (
                    float(bbox["min_x"]),
                    float(bbox["min_y"]),
                    float(bbox["max_x"]),
                    float(bbox["max_y"]),
                )
            except Exception:
                continue

    return out


def _extract_bounds_from_tile_manifest_payload(
    manifest: Dict[str, Any],
) -> Dict[str, Tuple[float, float, float, float]]:
    out: Dict[str, Tuple[float, float, float, float]] = {}
    for tile in manifest.get("tiles", []):
        if not isinstance(tile, dict):
            continue
        bbox = tile.get("bbox") or {}
        name = tile.get("id") or tile.get("file")
        if not isinstance(bbox, dict) or not name:
            continue
        try:
            out[str(name)] = (
                float(bbox["min_x"]),
                float(bbox["min_y"]),
                float(bbox["max_x"]),
                float(bbox["max_y"]),
            )
        except Exception:
            continue
    return out


def _load_tile_bounds_from_metadata(tiles_dir: str) -> Dict[str, Tuple[float, float, float, float]]:
    tiles_path = Path(tiles_dir)

    # Tiled outputs commonly live in <bundle_root>/tiles/*.xodr while the authoritative
    # metadata remains in <bundle_root>/tile_metadata.json. Check both locations so the
    # matcher can reuse canonical bounds instead of re-deriving them from XODRs that may
    # still carry legacy header offsets.
    metadata_candidates = [
        tiles_path / "tile_metadata.json",
        tiles_path.parent / "tile_metadata.json",
    ]
    for meta_path in metadata_candidates:
        if not meta_path.is_file():
            continue
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        out = _extract_bounds_from_tile_metadata_payload(data)
        if out:
            return out

    manifest_candidates = [
        tiles_path / "tile_manifest.json",
        tiles_path.parent / "tile_manifest.json",
    ]
    for manifest_path in manifest_candidates:
        if not manifest_path.is_file():
            continue
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            continue
        out = _extract_bounds_from_tile_manifest_payload(manifest)
        if out:
            return out

    return {}


def _read_tile_root(xodr_path: str) -> Optional[ET.Element]:
    try:
        return ET.parse(xodr_path).getroot()
    except Exception:
        return None


def _read_georef_text(root: ET.Element) -> str:
    header = root.find("header")
    if header is None:
        return ""
    geo = header.find("geoReference")
    valid, params_complete, norm = parse_georeference(geo.text if geo is not None else None)
    if not valid or not params_complete:
        return ""
    return str(norm or "")


def _read_header_offset(root: ET.Element) -> Dict[str, float]:
    header = root.find("header")
    if header is None:
        return {"x": 0.0, "y": 0.0, "hdg": 0.0}
    off = header.find("offset")
    if off is None:
        return {"x": 0.0, "y": 0.0, "hdg": 0.0}
    return {
        "x": _safe_float(off.get("x"), 0.0),
        "y": _safe_float(off.get("y"), 0.0),
        "hdg": _safe_float(off.get("hdg"), 0.0),
    }


def _apply_header_offset(
    x: float,
    y: float,
    offset: Dict[str, float],
) -> Tuple[float, float]:
    hdg = float(offset.get("hdg", 0.0))
    ox = float(offset.get("x", 0.0))
    oy = float(offset.get("y", 0.0))
    cos_h = math.cos(hdg)
    sin_h = math.sin(hdg)
    return (
        float(x) * cos_h - float(y) * sin_h + ox,
        float(x) * sin_h + float(y) * cos_h + oy,
    )


def _iter_planview_anchor_points(root: ET.Element) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    offset = _read_header_offset(root)
    for geom in root.findall(".//road/planView/geometry"):
        x_raw = geom.get("x")
        y_raw = geom.get("y")
        if x_raw is None or y_raw is None:
            continue
        try:
            px, py = _apply_header_offset(float(x_raw), float(y_raw), offset)
            points.append((float(px), float(py)))
        except Exception:
            continue
    return points


def _tile_bounds_from_xodr(xodr_path: str) -> Optional[Tuple[float, float, float, float]]:
    root = _read_tile_root(xodr_path)
    if root is None:
        return None
    points = _iter_planview_anchor_points(root)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _is_degenerate_bbox(bbox: Tuple[float, float, float, float]) -> bool:
    try:
        min_x, min_y, max_x, max_y = bbox
        return max_x <= min_x or max_y <= min_y
    except Exception:
        return True


def _bbox_corners(bbox: Tuple[float, float, float, float]) -> List[Tuple[float, float]]:
    min_x, min_y, max_x, max_y = bbox
    return [
        (min_x, min_y),
        (min_x, max_y),
        (max_x, min_y),
        (max_x, max_y),
    ]


def _transform_points(
    points: List[Tuple[float, float]],
    src_proj4: str,
    dst_crs: str,
) -> List[Tuple[float, float]]:
    if not points or not src_proj4 or not dst_crs:
        return []
    try:
        from pyproj import CRS, Transformer
    except Exception:
        return []

    try:
        transformer = Transformer.from_crs(
            CRS.from_user_input(src_proj4),
            CRS.from_user_input(dst_crs),
            always_xy=True,
        )
    except Exception:
        return []

    out: List[Tuple[float, float]] = []
    for x, y in points:
        try:
            tx, ty = transformer.transform(float(x), float(y))
            out.append((float(tx), float(ty)))
        except Exception:
            continue
    return out


def _bbox_from_points(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _centroid_from_points(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    if not points:
        return None
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    if _is_degenerate_bbox(a) or _is_degenerate_bbox(b):
        return 0.0
    geom_a = box(*a)
    geom_b = box(*b)
    union = geom_a.union(geom_b).area
    if union <= 0.0:
        return 0.0
    return float(geom_a.intersection(geom_b).area / union)


def intersection_bbox(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> Optional[Tuple[float, float, float, float]]:
    if _is_degenerate_bbox(a) or _is_degenerate_bbox(b):
        return None
    min_x = max(a[0], b[0])
    min_y = max(a[1], b[1])
    max_x = min(a[2], b[2])
    max_y = min(a[3], b[3])
    overlap = (min_x, min_y, max_x, max_y)
    if _is_degenerate_bbox(overlap):
        return None
    return overlap


def _centroid_distance_deg(
    a: Optional[Tuple[float, float]],
    b: Optional[Tuple[float, float]],
) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(math.hypot(a[0] - b[0], a[1] - b[1]))


def _build_tile_spatial_info(
    tile_path: str,
    metadata_bbox: Optional[Tuple[float, float, float, float]],
) -> Dict[str, Any]:
    root = _read_tile_root(tile_path)
    name = os.path.basename(tile_path)
    info: Dict[str, Any] = {
        "name": name,
        "path": tile_path,
        "index": _tile_index(name),
        "centroid_wgs84": None,
        "bbox_common": None,
        "spatial_ready": False,
    }
    if root is None:
        return info

    georef = _read_georef_text(root)
    points_local = _iter_planview_anchor_points(root)

    bbox_local = metadata_bbox
    if bbox_local is None:
        bbox_local = _bbox_from_points(points_local)

    if not georef:
        return info

    if metadata_bbox is not None and bbox_local is not None:
        centroid_points_local = _bbox_corners(bbox_local)
    else:
        centroid_points_local = points_local
        if not centroid_points_local and bbox_local is not None:
            centroid_points_local = _bbox_corners(bbox_local)

    centroid_wgs84 = _centroid_from_points(
        _transform_points(centroid_points_local, georef, _WGS84_CRS)
    )
    bbox_points_common = _transform_points(
        _bbox_corners(bbox_local) if bbox_local is not None else centroid_points_local,
        georef,
        _COMMON_TILE_CRS,
    )
    bbox_common = _bbox_from_points(bbox_points_common)

    info["centroid_wgs84"] = centroid_wgs84
    info["bbox_common"] = bbox_common
    info["spatial_ready"] = centroid_wgs84 is not None and bbox_common is not None
    return info


def _build_tile_info_index(tiles_dir: str) -> Dict[str, Dict[str, Any]]:
    metadata_bounds = _load_tile_bounds_from_metadata(tiles_dir)
    out: Dict[str, Dict[str, Any]] = {}
    for tile_path in sorted(glob.glob(os.path.join(tiles_dir, "tile_*.xodr"))):
        name = os.path.basename(tile_path)
        out[name] = _build_tile_spatial_info(tile_path, metadata_bounds.get(name))
    return out


def _nearest_index_match(
    manual_name: str,
    auto_infos: Dict[str, Dict[str, Any]],
    remaining_auto: set[str],
) -> Optional[str]:
    exact = manual_name if manual_name in remaining_auto else None
    if exact:
        return exact

    manual_idx = auto_infos.get(manual_name, {}).get("index")
    if manual_idx is None:
        manual_idx = _tile_index(manual_name)

    candidates: List[Tuple[int, int, str]] = []
    for auto_name in sorted(remaining_auto):
        auto_idx = auto_infos.get(auto_name, {}).get("index") or _tile_index(auto_name)
        dist = abs(int(auto_idx[0]) - int(manual_idx[0])) + abs(int(auto_idx[1]) - int(manual_idx[1]))
        candidates.append((dist, int(auto_idx[0]), auto_name))
    return candidates[0][2] if candidates else None


class TileMatcher:
    """Deterministic tile matcher with spatial centroid matching and index fallback."""

    @staticmethod
    def match_tiles(
        manual_dir: str,
        auto_dir: str,
        *,
        min_iou: float | None = None,
        prefer_id: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        matches, _ = TileMatcher.match_tiles_one_to_one(
            manual_dir,
            auto_dir,
            min_iou=min_iou,
            prefer_id=prefer_id,
        )
        return matches

    @staticmethod
    def match_tiles_one_to_one(
        manual_dir: str,
        auto_dir: str,
        *,
        min_iou: float | None = None,
        prefer_id: bool = True,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        if min_iou is None:
            min_iou = float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.5))
        max_centroid_dist_deg = float(
            getattr(SETTINGS, "TILE_MATCH_MAX_CENTROID_DIST_DEG", 0.01)
        )

        manual_infos = _build_tile_info_index(manual_dir)
        auto_infos = _build_tile_info_index(auto_dir)
        remaining_auto = set(auto_infos.keys())

        results: Dict[str, Dict[str, Any]] = {}
        matches_report: List[Dict[str, Any]] = []
        candidate_pairs = 0
        fallback_count = 0

        for manual_name in sorted(manual_infos.keys()):
            manual_info = manual_infos[manual_name]
            best_auto: Optional[str] = None
            best_dist: Optional[float] = None
            best_iou: float = -1.0

            for auto_name in sorted(remaining_auto):
                auto_info = auto_infos[auto_name]
                dist = _centroid_distance_deg(
                    manual_info.get("centroid_wgs84"),
                    auto_info.get("centroid_wgs84"),
                )
                if dist is None or dist > max_centroid_dist_deg:
                    continue
                candidate_pairs += 1
                iou = _iou(
                    manual_info.get("bbox_common"),
                    auto_info.get("bbox_common"),
                ) if manual_info.get("bbox_common") and auto_info.get("bbox_common") else 0.0
                candidate = (float(dist), -float(iou), auto_name)
                best = (
                    float(best_dist) if best_dist is not None else float("inf"),
                    -float(best_iou),
                    best_auto or "",
                )
                if candidate < best:
                    best_auto = auto_name
                    best_dist = float(dist)
                    best_iou = float(iou)

            match_method = "centroid_spatial"
            match_quality = "good"
            status = "matched_ok"

            if best_auto is None:
                fallback_auto = _nearest_index_match(manual_name, auto_infos, remaining_auto)
                if fallback_auto is None:
                    results[manual_name] = {
                        "match": None,
                        "iou": 0.0,
                        "status": "unmatched_no_candidate",
                        "match_quality": "unmatched_no_candidate",
                        "centroid_dist_deg": None,
                        "match_method": None,
                    }
                    continue
                fallback_count += 1
                best_auto = fallback_auto
                best_dist = _centroid_distance_deg(
                    manual_info.get("centroid_wgs84"),
                    auto_infos[best_auto].get("centroid_wgs84"),
                )
                best_iou = _iou(
                    manual_info.get("bbox_common"),
                    auto_infos[best_auto].get("bbox_common"),
                ) if manual_info.get("bbox_common") and auto_infos[best_auto].get("bbox_common") else 0.0
                match_method = "index_fallback"
                match_quality = "fallback_index_match"
                status = "matched_low_iou" if float(best_iou) < float(min_iou) else "matched_ok"
            elif float(best_iou) < float(min_iou):
                match_quality = "low_iou"
                status = "matched_low_iou"

            remaining_auto.discard(best_auto)
            match_entry = {
                "match": best_auto,
                "iou": round(float(best_iou), 4),
                "status": status,
                "match_quality": match_quality,
                "centroid_dist_deg": round(float(best_dist), 6) if best_dist is not None else None,
                "match_method": match_method,
            }
            results[manual_name] = match_entry
            matches_report.append(
                {
                    "manual": manual_name,
                    "auto": best_auto,
                    "iou": round(float(best_iou), 6),
                    "centroid_dist_deg": round(float(best_dist), 6) if best_dist is not None else None,
                    "match_quality": match_quality,
                    "status": status,
                    "match_method": match_method,
                }
            )

        num_matches = sum(1 for value in results.values() if value.get("match"))
        unmatched_manual = sum(1 for value in results.values() if not value.get("match"))
        report = {
            "pairing_method": "centroid_spatial",
            "one_to_one": True,
            "min_iou": float(min_iou),
            "min_iou_threshold": float(min_iou),
            "min_iou_used": float(min_iou),
            "max_centroid_dist_deg": float(max_centroid_dist_deg),
            "num_candidate_pairs": int(candidate_pairs),
            "num_matches": int(num_matches),
            "unmatched": {"manual": int(unmatched_manual), "auto": int(len(remaining_auto))},
            "index_fallback_matches": int(fallback_count),
            "excluded_manual_tiles": [],
            "excluded_auto_tiles": [],
            "exclusion_reasons": {},
            "matches": matches_report,
        }
        return results, report
