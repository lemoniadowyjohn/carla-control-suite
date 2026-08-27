# ultimate_pipeline/domain_gap/frechet_gap.py
"""
Discrete Fréchet distance between matched auto/manual road centerlines.

Thesis future-work item #14 (Chapter 9, `submission/thesis_source/Chapter9/chap9.tex`):
RMSE and Hausdorff distance are useful governed baselines but are sensitive to sampling and
road-decomposition mismatch; a curve-aware metric such as discrete Fréchet distance, computed
after robust road-segment correspondence, gives a more shape-sensitive comparison. The
delivered thesis computed this once as an un-committed, ad-hoc supplement (no script survives
in git history) against the OLD whole-network, uncropped, SE(2)-aligned "run_11" methodology
later found flawed (see THESIS_VS_CURRENT_STATE_COMPARISON_20260827.md and C22/C23/C26).

This module recomputes it against the CURRENT, correct methodology:
  1. Crop the auto road network to the manual map's own footprint via
     `ultimate_pipeline.domain_gap.local_registration` (hull or bbox) -- no artificial SE(2)
     best-fit alignment needed once the projection/offset handling is correct (verified
     repeatedly elsewhere this session).
  2. Reproject the cropped auto roads' points into MANUAL's own native CRS via the new
     `local_registration.transform_auto_points_to_manual_local` (mirror of the existing
     manual->auto transform `compute_local_registration` already used for cropping).
     Cropping alone is not enough: `compute_local_registration`'s existing metrics are
     distribution-level (each map's own road-length/curvature distribution, compared
     independently) and never need both maps' points in one common frame. A curve-similarity
     metric like Fréchet distance inherently needs point-level correspondence, so both
     centerlines must live in the same frame before comparing them.
  3. Match manual<->auto roads by nearest polyline, reusing
     `ultimate_pipeline.domain_gap.elevation_gap._match_roads` directly on profiles built in
     the (now-common) manual frame -- the same road-correspondence algorithm already used
     and tested for the elevation-gap metric, not a second independent implementation.
  4. Densely resample each matched road's centerline to a fixed arc-length spacing (default
     5 m, matching the original thesis supplement's parameter for direct comparability).
  5. Compute the standard Eiter-Mannila discrete Fréchet distance per matched pair, then
     report mean/median/p90 across all matched pairs.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Sequence, Tuple

from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points
from ultimate_pipeline.domain_gap.elevation_gap import (
    _RoadProfile,
    _build_road_profiles,
    _match_roads,
    _safe_float,
    _percentile,
    _mean,
)
from ultimate_pipeline.domain_gap.local_registration import (
    read_offset,
    read_georef_proj4,
    manual_geometry_bbox,
    manual_geometry_convex_hull,
    transform_manual_points_to_auto_local,
    transform_manual_bbox_to_auto_local,
    transform_auto_points_to_manual_local,
    crop_roads_to_polygon,
)

Point = Tuple[float, float]


# ---------------------------------------------------------------------------
# Discrete Fréchet distance (Eiter & Mannila, 1994)
# ---------------------------------------------------------------------------

def discrete_frechet_distance(p: Sequence[Point], q: Sequence[Point]) -> float:
    """Discrete Fréchet distance between two polylines `p` and `q`.

    Bottom-up dynamic-programming form of the standard recurrence (iterative, not
    recursive, so it doesn't hit Python's recursion limit on long road polylines).
    """
    if not p or not q:
        raise ValueError("discrete_frechet_distance: both curves must be non-empty")

    n, m = len(p), len(q)
    ca = [[0.0] * m for _ in range(n)]

    def dist(a: Point, b: Point) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    ca[0][0] = dist(p[0], q[0])
    for i in range(1, n):
        ca[i][0] = max(ca[i - 1][0], dist(p[i], q[0]))
    for j in range(1, m):
        ca[0][j] = max(ca[0][j - 1], dist(p[0], q[j]))
    for i in range(1, n):
        row = ca[i]
        prev_row = ca[i - 1]
        for j in range(1, m):
            row[j] = max(
                min(prev_row[j], prev_row[j - 1], row[j - 1]),
                dist(p[i], q[j]),
            )
    return float(ca[n - 1][m - 1])


# ---------------------------------------------------------------------------
# Fixed arc-length resampling
# ---------------------------------------------------------------------------

def resample_polyline_at_spacing(points: Sequence[Point], spacing_m: float) -> List[Point]:
    """Resample a piecewise-linear polyline to points spaced `spacing_m` apart by arc
    length, including the exact start and end points. Degenerate (zero-length) input
    collapses to a single point."""
    if not points:
        return []
    if len(points) == 1:
        return [points[0]]

    seg_lengths = [
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])
    ]
    total = sum(seg_lengths)
    if total <= 1e-12:
        return [points[0]]

    targets = []
    d = 0.0
    while d < total:
        targets.append(d)
        d += float(spacing_m)
    targets.append(total)

    out: List[Point] = []
    seg_idx = 0
    cum = 0.0
    for t in targets:
        while seg_idx < len(seg_lengths) - 1 and cum + seg_lengths[seg_idx] < t:
            cum += seg_lengths[seg_idx]
            seg_idx += 1
        seg_len = seg_lengths[seg_idx]
        frac = 0.0 if seg_len <= 1e-12 else (t - cum) / seg_len
        frac = max(0.0, min(1.0, frac))
        a, b = points[seg_idx], points[seg_idx + 1]
        out.append((a[0] + frac * (b[0] - a[0]), a[1] + frac * (b[1] - a[1])))
    return out


# ---------------------------------------------------------------------------
# Dense road-centerline sampling in a road's own LOCAL frame (line/arc formulas match the
# ones independently verified elsewhere this session, e.g. xodr_cropper_gps.py; paramPoly3
# reuses the shared "authoritative" sampler).
# ---------------------------------------------------------------------------

def _dense_sample_geometry(geom: ET.Element, step_m: float) -> List[Point]:
    x0 = _safe_float(geom.get("x"), 0.0)
    y0 = _safe_float(geom.get("y"), 0.0)
    hdg = _safe_float(geom.get("hdg"), 0.0)
    length = max(0.0, _safe_float(geom.get("length"), 0.0))
    n = max(2, int(math.ceil(length / max(float(step_m), 1e-6))) + 1)
    t_values = [i / (n - 1) for i in range(n)]

    arc = geom.find("arc")
    if arc is not None:
        k = _safe_float(arc.get("curvature"), 0.0)
        if abs(k) <= 1e-12:
            return [(x0 + length * t * math.cos(hdg), y0 + length * t * math.sin(hdg)) for t in t_values]
        sin_h0, cos_h0 = math.sin(hdg), math.cos(hdg)
        points = []
        for t in t_values:
            s = length * t
            hs = hdg + k * s
            points.append((x0 + (math.sin(hs) - sin_h0) / k, y0 - (math.cos(hs) - cos_h0) / k))
        return points

    if geom.find("paramPoly3") is not None:
        return sample_parampoly3_points(geom, x0, y0, hdg, length, t_values)

    return [(x0 + length * t * math.cos(hdg), y0 + length * t * math.sin(hdg)) for t in t_values]


def dense_road_centerline_local(road: ET.Element, step_m: float = 1.0) -> List[Point]:
    """Densely-sampled (default 1 m step, finer than the final resample target) centerline
    for `road` in its OWN raw local frame (no offset/reprojection applied), concatenated
    across all its planView geometry segments in order."""
    points: List[Point] = []
    for geom in road.findall("./planView/geometry"):
        points.extend(_dense_sample_geometry(geom, step_m))
    return points


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def compute_frechet_gap(
    auto_xodr: str,
    manual_xodr: str,
    *,
    spacing_m: float = 5.0,
    match_threshold_m: float = 50.0,
    footprint: str = "hull",
    coarse_step_m: float = 20.0,
    dense_step_m: float = 1.0,
) -> Dict[str, Any]:
    """Discrete Fréchet distance per matched manual<->auto road pair, after cropping auto to
    the manual footprint and reprojecting the cropped roads into manual's own CRS (current,
    correct RQ1 methodology -- see module docstring).

    `footprint`: "hull" (default, matches `local_registration.compute_local_registration`)
    or "bbox" (wider, legacy comparison -- also usable for tiny synthetic test fixtures
    where a convex hull would otherwise degenerate).
    `coarse_step_m`: sample spacing used only for road-to-road MATCHING (cheap, doesn't need
    to be as fine as the final Fréchet computation's `spacing_m`).
    """
    if footprint not in ("hull", "bbox"):
        raise ValueError(f"footprint must be 'hull' or 'bbox', got {footprint!r}")

    auto_root = ET.parse(auto_xodr).getroot()
    manual_root = ET.parse(manual_xodr).getroot()

    auto_off = read_offset(auto_root)
    auto_proj = read_georef_proj4(auto_root)
    manual_proj = read_georef_proj4(manual_root)

    if footprint == "hull":
        hull_pts = manual_geometry_convex_hull(manual_root)
        poly = transform_manual_points_to_auto_local(hull_pts, manual_proj, auto_proj, auto_off)
    else:
        manual_bbox = manual_geometry_bbox(manual_root)
        poly = transform_manual_bbox_to_auto_local(manual_bbox, manual_proj, auto_proj, auto_off)

    auto_roads_all = auto_root.findall("road")
    auto_roads_cropped = crop_roads_to_polygon(auto_roads_all, poly)
    manual_roads_all = manual_root.findall("road")

    if not auto_roads_cropped:
        return {
            "matched_pair_count": 0,
            "mean_m": None,
            "median_m": None,
            "p90_m": None,
            "spacing_m": float(spacing_m),
            "match_threshold_m": float(match_threshold_m),
            "footprint": footprint,
            "auto_road_count_total": len(auto_roads_all),
            "auto_road_count_cropped": 0,
            "manual_road_count": len(manual_roads_all),
        }

    # --- Coarse-sample every cropped auto road (its own local frame), batch-reproject all
    # points into manual's CRS in ONE transform call (much faster than per-road/per-point). ---
    coarse_local_points: List[Point] = []
    road_ranges: List[Tuple[ET.Element, int, int]] = []
    for road in auto_roads_cropped:
        pts = dense_road_centerline_local(road, step_m=coarse_step_m)
        start = len(coarse_local_points)
        coarse_local_points.extend(pts)
        road_ranges.append((road, start, len(coarse_local_points)))

    coarse_manual_frame = transform_auto_points_to_manual_local(
        coarse_local_points, auto_proj4=auto_proj, auto_offset=auto_off, manual_proj4=manual_proj,
    )

    auto_profiles: List[_RoadProfile] = []
    for road, start, end in road_ranges:
        pts = coarse_manual_frame[start:end]
        if not pts:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        auto_profiles.append(
            _RoadProfile(
                road_id=str(road.get("id") or ""),
                length_m=max(0.0, _safe_float(road.get("length"), 0.0)),
                centroid_xy=(cx, cy),
                polyline_xy=tuple(pts),
                elevation_segments=(),
                flat=False,
            )
        )

    manual_profiles = _build_road_profiles(manual_xodr, flat_eps_m=1e-6)

    matches = _match_roads(
        manual_profiles,
        auto_profiles,
        max_match_distance_m=float(match_threshold_m),
        candidate_centroid_distance_m=max(200.0, float(match_threshold_m) * 2.0),
    )

    if not matches:
        return {
            "matched_pair_count": 0,
            "mean_m": None,
            "median_m": None,
            "p90_m": None,
            "spacing_m": float(spacing_m),
            "match_threshold_m": float(match_threshold_m),
            "footprint": footprint,
            "auto_road_count_total": len(auto_roads_all),
            "auto_road_count_cropped": len(auto_roads_cropped),
            "manual_road_count": len(manual_roads_all),
        }

    manual_by_id = {r.get("id"): r for r in manual_roads_all}
    auto_by_id = {r.get("id"): r for r in auto_roads_cropped}

    distances: List[float] = []
    for manual_profile, auto_profile, _match_dist in matches:
        manual_road = manual_by_id.get(manual_profile.road_id)
        auto_road = auto_by_id.get(auto_profile.road_id)
        if manual_road is None or auto_road is None:
            continue
        manual_dense = dense_road_centerline_local(manual_road, step_m=dense_step_m)
        auto_dense_local = dense_road_centerline_local(auto_road, step_m=dense_step_m)
        auto_dense_manual_frame = transform_auto_points_to_manual_local(
            auto_dense_local, auto_proj4=auto_proj, auto_offset=auto_off, manual_proj4=manual_proj,
        )
        manual_rs = resample_polyline_at_spacing(manual_dense, spacing_m)
        auto_rs = resample_polyline_at_spacing(auto_dense_manual_frame, spacing_m)
        if not manual_rs or not auto_rs:
            continue
        distances.append(discrete_frechet_distance(manual_rs, auto_rs))

    return {
        "matched_pair_count": len(distances),
        "mean_m": _mean(distances),
        "median_m": _percentile(distances, 50.0),
        "p90_m": _percentile(distances, 90.0),
        "spacing_m": float(spacing_m),
        "match_threshold_m": float(match_threshold_m),
        "footprint": footprint,
        "auto_road_count_total": len(auto_roads_all),
        "auto_road_count_cropped": len(auto_roads_cropped),
        "manual_road_count": len(manual_roads_all),
    }


def _main() -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Compute and persist the local Frechet-distance evidence row.")
    parser.add_argument("auto_xodr")
    parser.add_argument("manual_xodr")
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument("--spacing-m", type=float, default=5.0)
    parser.add_argument("--match-threshold-m", type=float, default=50.0)
    parser.add_argument("--footprint", default="hull", choices=("hull", "bbox"))
    args = parser.parse_args()

    result = compute_frechet_gap(
        args.auto_xodr, args.manual_xodr,
        spacing_m=args.spacing_m, match_threshold_m=args.match_threshold_m, footprint=args.footprint,
    )
    from pathlib import Path

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_json.dumps(result, indent=2), encoding="utf-8")
    print(f"[frechet_gap] {result}")
    print(f"[frechet_gap] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
