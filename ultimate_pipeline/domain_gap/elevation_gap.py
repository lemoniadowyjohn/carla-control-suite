from __future__ import annotations

import math
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return float(parsed)


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(statistics.fmean(float(v) for v in values))


def _pstdev(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return float(statistics.pstdev(float(v) for v in values))


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pct = max(0.0, min(100.0, float(pct)))
    pos = (len(ordered) - 1) * (pct / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _rmse(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(math.sqrt(sum(float(v) * float(v) for v in values) / float(len(values))))


def _read_header_offset_xy(root: ET.Element) -> Tuple[float, float]:
    header = root.find("header")
    if header is None:
        return 0.0, 0.0
    offset = header.find("offset")
    if offset is None:
        return 0.0, 0.0
    return _safe_float(offset.get("x"), 0.0), _safe_float(offset.get("y"), 0.0)


def _effective_header_offset_xy(root: ET.Element) -> Tuple[float, float]:
    offset_x, offset_y = _read_header_offset_xy(root)
    if abs(offset_x) <= 1e-9 and abs(offset_y) <= 1e-9:
        return 0.0, 0.0

    # Aligned XODRs can keep the historical header offset while their
    # planView geometry has already been rewritten into absolute projected
    # coordinates. Re-applying the offset here would double-shift the map.
    geom_count = 0
    max_abs_geom = 0.0
    for idx, geom in enumerate(root.findall("./road/planView/geometry")):
        geom_count += 1
        max_abs_geom = max(
            max_abs_geom,
            abs(_safe_float(geom.get("x"), 0.0)),
            abs(_safe_float(geom.get("y"), 0.0)),
        )
        if idx >= 255:
            break
    if max_abs_geom >= 100000.0 and max(abs(offset_x), abs(offset_y)) >= 1000.0:
        # Global-frame geometry with a large offset: offset already baked in.
        return 0.0, 0.0
    if geom_count == 0 and max(abs(offset_x), abs(offset_y)) > 1e-9:
        # EG-001: No geometry elements found — cannot determine coordinate frame.
        # Suppress offset as safe default to avoid phantom double-shift.
        return 0.0, 0.0
    return offset_x, offset_y


def _parse_elevation_segments(road: ET.Element) -> List[Tuple[float, float, float, float, float]]:
    profile = road.find("elevationProfile")
    if profile is None:
        return []
    segments: List[Tuple[float, float, float, float, float]] = []
    for el in profile.findall("elevation"):
        segments.append(
            (
                _safe_float(el.get("s"), 0.0),
                _safe_float(el.get("a"), 0.0),
                _safe_float(el.get("b"), 0.0),
                _safe_float(el.get("c"), 0.0),
                _safe_float(el.get("d"), 0.0),
            )
        )
    segments.sort(key=lambda item: item[0])
    return segments


def _elevation_at_s(
    segments: Sequence[Tuple[float, float, float, float, float]],
    s_abs: float,
) -> float:
    if not segments:
        return 0.0
    current = segments[0]
    for segment in segments:
        if s_abs >= segment[0]:
            current = segment
        else:
            break
    s0, a, b, c, d = current
    ds = max(0.0, float(s_abs) - float(s0))
    return float(a + b * ds + c * ds * ds + d * ds * ds * ds)


def _sample_line(x0: float, y0: float, hdg: float, length: float, t_values: Iterable[float]) -> List[Tuple[float, float]]:
    return [
        (
            x0 + (float(length) * float(t) * math.cos(hdg)),
            y0 + (float(length) * float(t) * math.sin(hdg)),
        )
        for t in t_values
    ]


def _sample_arc(
    x0: float,
    y0: float,
    hdg: float,
    length: float,
    curvature: float,
    t_values: Iterable[float],
) -> List[Tuple[float, float]]:
    k = float(curvature)
    if abs(k) <= 1e-12:
        return _sample_line(x0, y0, hdg, length, t_values)
    points: List[Tuple[float, float]] = []
    for t in t_values:
        ds = float(length) * float(t)
        theta = hdg + k * ds
        xx = x0 + (math.sin(theta) - math.sin(hdg)) / k
        yy = y0 - (math.cos(theta) - math.cos(hdg)) / k
        points.append((xx, yy))
    return points


def _sample_geometry_points(geom: ET.Element, offset_x: float, offset_y: float) -> List[Tuple[float, float]]:
    x0 = _safe_float(geom.get("x"), 0.0) + float(offset_x)
    y0 = _safe_float(geom.get("y"), 0.0) + float(offset_y)
    hdg = _safe_float(geom.get("hdg"), 0.0)
    length = max(0.0, _safe_float(geom.get("length"), 0.0))
    t_values = (0.0, 0.5, 1.0)
    if geom.find("arc") is not None:
        curvature = _safe_float(geom.find("arc").get("curvature"), 0.0)
        return _sample_arc(x0, y0, hdg, length, curvature, t_values)
    if geom.find("paramPoly3") is not None:
        return sample_parampoly3_points(geom, x0, y0, hdg, length, t_values)
    return _sample_line(x0, y0, hdg, length, t_values)


def _road_sample_positions(length_m: float, samples_per_road: int) -> List[float]:
    if samples_per_road <= 1 or length_m <= 0.0:
        return [0.0]
    denom = float(samples_per_road - 1)
    return [float(length_m) * (idx / denom) for idx in range(samples_per_road)]


@dataclass(frozen=True)
class _RoadProfile:
    road_id: str
    length_m: float
    centroid_xy: Tuple[float, float]
    polyline_xy: Tuple[Tuple[float, float], ...]
    elevation_segments: Tuple[Tuple[float, float, float, float, float], ...]
    flat: bool


def _build_road_profiles(xodr_path: str, *, flat_eps_m: float) -> List[_RoadProfile]:
    root = ET.parse(xodr_path).getroot()
    offset_x, offset_y = _effective_header_offset_xy(root)
    profiles: List[_RoadProfile] = []
    for road in root.findall("road"):
        road_id = str(road.get("id") or "")
        length_m = max(0.0, _safe_float(road.get("length"), 0.0))
        points: List[Tuple[float, float]] = []
        for geom in road.findall("./planView/geometry"):
            points.extend(_sample_geometry_points(geom, offset_x, offset_y))
        if not points:
            continue
        centroid_x = sum(pt[0] for pt in points) / float(len(points))
        centroid_y = sum(pt[1] for pt in points) / float(len(points))
        elevation_segments = tuple(_parse_elevation_segments(road))
        sample_positions = _road_sample_positions(length_m, 10)
        z_samples = [_elevation_at_s(elevation_segments, s_abs) for s_abs in sample_positions]
        z_range = (max(z_samples) - min(z_samples)) if z_samples else 0.0
        profiles.append(
            _RoadProfile(
                road_id=road_id,
                length_m=length_m,
                centroid_xy=(centroid_x, centroid_y),
                polyline_xy=tuple(points),
                elevation_segments=elevation_segments,
                flat=bool(z_range <= flat_eps_m),
            )
        )
    return profiles


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return float(math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])))


def _min_point_set_distance(
    points_a: Sequence[Tuple[float, float]],
    points_b: Sequence[Tuple[float, float]],
) -> float:
    best = float("inf")
    for point_a in points_a:
        for point_b in points_b:
            dist = _distance(point_a, point_b)
            if dist < best:
                best = dist
                if best <= 0.0:
                    return 0.0
    return float(best)


def _match_roads(
    manual_roads: Sequence[_RoadProfile],
    auto_roads: Sequence[_RoadProfile],
    *,
    max_match_distance_m: float,
    candidate_centroid_distance_m: float,
) -> List[Tuple[_RoadProfile, _RoadProfile, float]]:
    remaining_auto = list(auto_roads)
    matches: List[Tuple[_RoadProfile, _RoadProfile, float]] = []
    for manual in manual_roads:
        best_index: Optional[int] = None
        best_distance = float("inf")
        for idx, auto in enumerate(remaining_auto):
            centroid_dist = _distance(manual.centroid_xy, auto.centroid_xy)
            # EG-002: when exactly one candidate remains, bypass the centroid
            # pre-filter — let polyline distance decide. Prevents single-road
            # tiles (common in smoke-test XODRs) from being incorrectly dropped.
            if len(remaining_auto) > 1 and centroid_dist > float(candidate_centroid_distance_m):
                continue
            dist = _min_point_set_distance(manual.polyline_xy, auto.polyline_xy)
            if dist < best_distance:
                best_distance = dist
                best_index = idx
        if best_index is None or best_distance > float(max_match_distance_m):
            continue
        matched_auto = remaining_auto.pop(best_index)
        matches.append((manual, matched_auto, float(best_distance)))
    return matches


class ElevationGap:
    @staticmethod
    def compute(
        manual_xodr: str,
        auto_xodr: str,
        *,
        samples_per_road: int = 10,
        max_match_distance_m: float = 100.0,
        flat_eps_m: float = 1e-6,
    ) -> Dict[str, Any]:
        manual_roads = _build_road_profiles(manual_xodr, flat_eps_m=flat_eps_m)
        auto_roads = _build_road_profiles(auto_xodr, flat_eps_m=flat_eps_m)
        if not manual_roads or not auto_roads:
            return {
                "disabled": True,
                "reason": "missing_road_profiles",
                "supplementary": True,
                "primary_artifact_is_planar": True,
                "manual_road_count": int(len(manual_roads)),
                "auto_road_count": int(len(auto_roads)),
            }

        matches = _match_roads(
            manual_roads,
            auto_roads,
            max_match_distance_m=max_match_distance_m,
            candidate_centroid_distance_m=max(200.0, float(max_match_distance_m) * 2.0),
        )
        pct_roads_flat_manual = float(sum(1 for road in manual_roads if road.flat) / len(manual_roads))
        pct_roads_flat_auto = float(sum(1 for road in auto_roads if road.flat) / len(auto_roads))
        if not matches:
            return {
                "disabled": True,
                "reason": "no_matched_roads",
                "supplementary": True,
                "primary_artifact_is_planar": True,
                "manual_road_count": int(len(manual_roads)),
                "auto_road_count": int(len(auto_roads)),
                "matched_count": 0,
                "matched_road_pairs": 0,
                "max_match_distance_m": float(max_match_distance_m),
                "match_distance_method": "sampled_polyline_min_distance",
                "candidate_centroid_distance_m": max(200.0, float(max_match_distance_m) * 2.0),
                "pct_roads_flat_manual": pct_roads_flat_manual,
                "pct_roads_flat_auto": pct_roads_flat_auto,
            }

        all_deltas: List[float] = []
        per_road_rmse: List[float] = []
        for manual, auto, _distance_m in matches:
            manual_s = _road_sample_positions(manual.length_m, samples_per_road)
            auto_s = _road_sample_positions(auto.length_m, samples_per_road)
            local_deltas: List[float] = []
            for s_manual, s_auto in zip(manual_s, auto_s):
                delta = _elevation_at_s(auto.elevation_segments, s_auto) - _elevation_at_s(
                    manual.elevation_segments,
                    s_manual,
                )
                local_deltas.append(float(delta))
            all_deltas.extend(local_deltas)
            per_road_rmse.append(_rmse(local_deltas) or 0.0)

        match_distances = [distance_m for _manual, _auto, distance_m in matches]
        return {
            "disabled": False,
            "supplementary": True,
            "primary_artifact_is_planar": True,
            "samples_per_road": int(samples_per_road),
            "max_match_distance_m": float(max_match_distance_m),
            "candidate_centroid_distance_m": max(200.0, float(max_match_distance_m) * 2.0),
            "match_distance_method": "sampled_polyline_min_distance",
            "manual_road_count": int(len(manual_roads)),
            "auto_road_count": int(len(auto_roads)),
            "matched_count": int(len(matches)),
            "matched_road_pairs": int(len(matches)),
            "mean_delta_m": _mean(all_deltas),
            "std_delta_m": _pstdev(all_deltas),
            "rmse_m": _rmse(all_deltas),
            "per_road_rmse_p50_m": _percentile(per_road_rmse, 50.0),
            "per_road_rmse_p95_m": _percentile(per_road_rmse, 95.0),
            "pct_roads_flat_manual": pct_roads_flat_manual,
            "pct_roads_flat_auto": pct_roads_flat_auto,
            "match_distance_mean_m": _mean(match_distances),
            "match_distance_p95_m": _percentile(match_distances, 95.0),
        }


def compute_elevation_gap(manual_xodr: str, auto_xodr: str, **kwargs: Any) -> Dict[str, Any]:
    return ElevationGap.compute(manual_xodr, auto_xodr, **kwargs)
