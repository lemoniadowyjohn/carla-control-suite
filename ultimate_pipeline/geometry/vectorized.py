#!/usr/bin/env python3
"""Vectorized lane/geometry math - eliminates scalar loops."""
from __future__ import annotations

import math
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GeometrySegment:
    """A single geometry segment (line, arc, or spiral)."""
    s_start: float
    x_start: float
    y_start: float
    hdg_start: float
    length: float
    type: str  # "line", "arc", "spiral"
    params: dict = field(default_factory=dict)


@dataclass
class RoadGeometry:
    """Complete road geometry with vectorized operations."""
    segments: list[GeometrySegment] = field(default_factory=list)
    total_length: float = 0.0

    def __post_init__(self):
        self.total_length = sum(s.length for s in self.segments)

    @classmethod
    def from_xodr_geometries(cls, geometries: list) -> "RoadGeometry":
        """Build from XODR geometry elements."""
        segments = []
        for g in geometries:
            seg = GeometrySegment(
                s_start=g.get("s", 0),
                x_start=g.get("x", 0),
                y_start=g.get("y", 0),
                hdg_start=g.get("hdg", 0),
                length=g.get("length", 0),
                type=g.get("type", "line"),
                params=g.get("params", {}),
            )
            segments.append(seg)
        return cls(segments=segments)

    def sample_at(self, s: np.ndarray) -> dict[str, np.ndarray]:
        """Vectorized sampling at multiple s positions.
        
        Args:
            s: Array of s positions (distance along road) [N]
            
        Returns:
            Dict with 'x', 'y', 'hdg', 'segment_idx' arrays [N]
        """
        s = np.asarray(s)
        n = len(s)
        x = np.zeros(n, dtype=np.float64)
        y = np.zeros(n, dtype=np.float64)
        hdg = np.zeros(n, dtype=np.float64)
        seg_idx = np.zeros(n, dtype=np.int32)

        # For each segment, find s values that fall in it
        for i, seg in enumerate(self.segments):
            s0 = seg.s_start
            s1 = seg.s_start + seg.length
            mask = (s >= s0) & (s < s1) if i < len(self.segments) - 1 else (s >= s0) & (s <= s1)

            if not np.any(mask):
                continue

            seg_s = s[mask] - seg.s_start
            seg_x, seg_y, seg_hdg = self._eval_segment(seg, seg_s)

            x[mask] = seg_x
            y[mask] = seg_y
            hdg[mask] = seg_hdg
            seg_idx[mask] = i

        return {"x": x, "y": y, "hdg": hdg, "segment_idx": seg_idx}

    def _eval_segment(self, seg: GeometrySegment, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Evaluate a single segment at multiple t positions (relative to segment start)."""
        t = np.asarray(t)
        if seg.type == "line":
            return self._eval_line(seg, t)
        elif seg.type == "arc":
            return self._eval_arc(seg, t)
        elif seg.type == "spiral":
            return self._eval_spiral(seg, t)
        elif seg.type == "poly3":
            return self._eval_poly3(seg, t)
        else:
            # Unknown type - treat as line
            return self._eval_line(seg, t)

    @staticmethod
    def _eval_line(seg: GeometrySegment, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cos_h = math.cos(seg.hdg_start)
        sin_h = math.sin(seg.hdg_start)
        x = seg.x_start + t * cos_h
        y = seg.y_start + t * sin_h
        hdg = np.full_like(t, seg.hdg_start)
        return x, y, hdg

    @staticmethod
    def _eval_arc(seg: GeometrySegment, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        curv = seg.params.get("curvature", 0.0)
        if abs(curv) < 1e-12:
            # Nearly straight - use line
            cos_h = math.cos(seg.hdg_start)
            sin_h = math.sin(seg.hdg_start)
            x = seg.x_start + t * cos_h
            y = seg.y_start + t * sin_h
            hdg = np.full_like(t, seg.hdg_start)
            return x, y, hdg

        r = 1.0 / curv
        theta = curv * t
        cos_h0 = math.cos(seg.hdg_start)
        sin_h0 = math.sin(seg.hdg_start)
        cos_h = np.cos(seg.hdg_start + theta)
        sin_h = np.sin(seg.hdg_start + theta)

        x = seg.x_start + r * (sin_h - sin_h0)
        y = seg.y_start - r * (cos_h - cos_h0)
        hdg = seg.hdg_start + theta
        return x, y, hdg

    @staticmethod
    def _eval_spiral(seg: GeometrySegment, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        curv_start = seg.params.get("curvStart", 0.0)
        curv_end = seg.params.get("curvEnd", 0.0)
        length = seg.length

        if length <= 0:
            return np.full_like(t, seg.x_start), np.full_like(t, seg.y_start), np.full_like(t, seg.hdg_start)

        if abs(curv_end - curv_start) < 1e-12:
            # Constant curvature - treat as arc
            seg2 = GeometrySegment(
                s_start=0, x_start=seg.x_start, y_start=seg.y_start,
                hdg_start=seg.hdg_start, length=length,
                type="arc", params={"curvature": curv_start}
            )
            return RoadGeometry._eval_arc(seg2, t)

        # Linear curvature change - use numerical integration
        # Vectorized using small step integration
        steps = max(2, int(length / 0.5))  # ~0.5m steps
        step_t = np.linspace(0, length, steps + 1)
        step_dt = step_t[1] - step_t[0]

        # Precompute curvature at each step
        curv = curv_start + (curv_end - curv_start) * (step_t[:-1] / length)
        theta_step = curv * step_dt

        # Integrate
        x = np.full_like(t, seg.x_start, dtype=np.float64)
        y = np.full_like(t, seg.y_start, dtype=np.float64)
        hdg = np.full_like(t, seg.hdg_start, dtype=np.float64)

        # For each query t, find enclosing step and interpolate
        for i, ti in enumerate(t):
            if ti <= 0:
                continue
            step_idx = min(int(ti / step_dt), steps - 1)
            if step_idx < 0:
                continue

            # Integrate up to this step
            hdg_acc = seg.hdg_start
            x_acc = seg.x_start
            y_acc = seg.y_start

            for step in range(step_idx):
                theta = theta_step[step]
                hdg_mid = hdg_acc + theta / 2
                x_acc += step_dt * math.cos(hdg_mid)
                y_acc += step_dt * math.sin(hdg_mid)
                hdg_acc += theta

            # Remainder within step
            rem = ti - step_idx * step_dt
            if rem > 0:
                theta_rem = curv[step_idx] * rem
                hdg_mid = hdg_acc + theta_rem / 2
                x_acc += rem * math.cos(hdg_mid)
                y_acc += rem * math.sin(hdg_mid)
                hdg_acc += theta_rem

            x[i] = x_acc
            y[i] = y_acc
            hdg[i] = hdg_acc

        return x, y, hdg

    @staticmethod
    def _eval_poly3(seg: GeometrySegment, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # Polynomial: x = a + b*t + c*t^2 + d*t^3
        # But we need both x and y - poly3 in OpenDRIVE is typically for elevation/superelevation
        # For plan view, fall back to line approximation
        return RoadGeometry._eval_line(
            GeometrySegment(0, seg.x_start, seg.y_start, seg.hdg_start, seg.length, "line", {}),
            t
        )


# Vectorized lane operations
def lane_offset_vectorized(
    lane_widths: np.ndarray,
    lane_offsets: np.ndarray,
    lane_ids: np.ndarray,
    reference_lane: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized lane offset computation.
    
    Args:
        lane_widths: [N_lanes] lane widths
        lane_offsets: [N_lanes] lane offsets from reference
        lane_ids: [N_lanes] lane IDs
        reference_lane: Lane ID to use as reference (default 0 = center)
        
    Returns:
        (left_offsets, right_offsets) arrays [N_lanes]
    """
    widths = np.asarray(lane_widths)
    offsets = np.asarray(lane_offsets)

    # Center line is at offset 0
    center_idx = np.where(lane_ids == reference_lane)[0]
    if len(center_idx) == 0:
        center_idx = 0
    else:
        center_idx = center_idx[0]

    ref_offset = offsets[center_idx] if len(offsets) > center_idx else 0

    # Compute cumulative width from center to each lane
    left_offsets = offsets - ref_offset
    right_offsets = offsets - ref_offset

    return left_offsets, right_offsets


def heading_vectorized(hdg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized heading to unit vector.
    
    Args:
        hdg: Array of headings in radians [N]
        
    Returns:
        (cos_h, sin_h) arrays [N]
    """
    hdg = np.asarray(hdg)
    return np.cos(hdg), np.sin(hdg)


def rotate_vectorized(
    points: np.ndarray,
    cos_h: np.ndarray,
    sin_h: np.ndarray,
) -> np.ndarray:
    """Vectorized rotation of points by headings.
    
    Args:
        points: Array of shape [N, 2] or [2, N]
        cos_h: Cosines of headings [N]
        sin_h: Sines of headings [N]
        
    Returns:
        Rotated points [N, 2]
    """
    points = np.asarray(points)
    if points.ndim == 1:
        points = points.reshape(-1, 2)

    if points.shape[1] != 2:
        points = points.T

    # Rotation matrix: [cos -sin; sin cos]
    x_rot = points[:, 0] * cos_h - points[:, 1] * sin_h
    y_rot = points[:, 0] * sin_h + points[:, 1] * cos_h

    return np.column_stack([x_rot, y_rot])


def transform_to_local_vectorized(
    global_coords: np.ndarray,
    origin: tuple[float, float],
    cos_h: float,
    sin_h: float,
) -> np.ndarray:
    """Vectorized global to local coordinate transform."""
    coords = np.asarray(global_coords)
    if coords.ndim == 1:
        coords = coords.reshape(-1, 2)

    local = coords - np.array(origin)
    return rotate_vectorized(local, np.full(len(coords), cos_h), np.full(len(coords), sin_h))


def lane_centerline_vectorized(
    road_centerline: dict[str, np.ndarray],
    lane_offsets: np.ndarray,
    lane_widths: np.ndarray,
    lane_ids: np.ndarray,
) -> dict[str, np.ndarray]:
    """Vectorized lane centerline computation from road centerline.
    
    Args:
        road_centerline: Dict with 'x', 'y', 'hdg' arrays [N_points]
        lane_offsets: [N_lanes] lateral offsets from road center
        lane_widths: [N_lanes] lane widths
        lane_ids: [N_lanes] lane IDs
        
    Returns:
        Dict with lane_id -> {'x', 'y', 'hdg'} for each lane
    """
    x = road_centerline["x"]
    y = road_centerline["y"]
    hdg = road_centerline["hdg"]
    n = len(x)

    cos_h, sin_h = heading_vectorized(hdg)

    results = {}
    for i, (offset, width, lane_id) in enumerate(zip(lane_offsets, lane_widths, lane_ids)):
        # Lane center is at offset + width/2 from previous lane
        lateral = offset + width / 2

        # Apply lateral offset perpendicular to heading
        # Perpendicular vector: (-sin_h, cos_h)
        lane_x = x + lateral * (-sin_h)
        lane_y = y + lateral * cos_h

        results[lane_id] = {"x": lane_x, "y": lane_y, "hdg": hdg.copy()}

    return results


# Vectorized spatial operations
def distance_vectorized(
    points1: np.ndarray,
    points2: np.ndarray,
) -> np.ndarray:
    """Vectorized Euclidean distance between two point arrays.
    
    Args:
        points1: [N, 2] or [N]
        points2: [M, 2] or [M] or [2]
        
    Returns:
        Distance matrix [N, M] or [N] if points2 is single point
    """
    p1 = np.asarray(points1)
    p2 = np.asarray(points2)

    if p1.ndim == 1:
        p1 = p1.reshape(-1, 2)
    if p2.ndim == 1:
        p2 = p2.reshape(-1, 2)

    # Broadcasting: [N, 1, 2] - [1, M, 2] -> [N, M, 2]
    diff = p1[:, np.newaxis, :] - p2[np.newaxis, :, :]
    return np.sqrt(np.sum(diff**2, axis=2))


def nearest_neighbor_vectorized(
    query_points: np.ndarray,
    reference_points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized nearest neighbor search.
    
    Args:
        query_points: [N, 2]
        reference_points: [M, 2]
        
    Returns:
        (indices, distances) - indices of nearest reference point for each query, and distances
    """
    dists = distance_vectorized(query_points, reference_points)
    indices = np.argmin(dists, axis=1)
    distances = dists[np.arange(len(query_points)), indices]
    return indices, distances


def hausdorff_distance_vectorized(
    points1: np.ndarray,
    points2: np.ndarray,
    directed: bool = False,
) -> float:
    """Vectorized Hausdorff distance.
    
    Args:
        points1: [N, 2]
        points2: [M, 2]
        directed: If True, compute directed Hausdorff (points1 -> points2)
        
    Returns:
        Hausdorff distance
    """
    dists = distance_vectorized(points1, points2)
    min_dists_1 = np.min(dists, axis=1)
    hd_1_to_2 = np.max(min_dists_1)

    if directed:
        return hd_1_to_2

    min_dists_2 = np.min(dists, axis=0)
    hd_2_to_1 = np.max(min_dists_2)
    return max(hd_1_to_2, hd_2_to_1)


# Coordinate system transformations
def project_lonlat_to_local(
    lons: np.ndarray,
    lats: np.ndarray,
    header_offset: tuple[float, float],
    proj_string: str = "+proj=tmerc +datum=WGS84 +units=m +no_defs",
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized lon/lat to local projection."""
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", proj_string, always_xy=True)
    gx, gy = transformer.transform(lons, lats)
    ox, oy = header_offset
    return gx - ox, gy - oy


def project_local_to_lonlat(
    xs: np.ndarray,
    ys: np.ndarray,
    header_offset: tuple[float, float],
    proj_string: str = "+proj=tmerc +datum=WGS84 +units=m +no_defs",
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized local to lon/lat projection."""
    from pyproj import Transformer

    transformer = Transformer.from_crs(proj_string, "EPSG:4326", always_xy=True)
    gx = xs + header_offset[0]
    gy = ys + header_offset[1]
    return transformer.transform(gx, gy)


# Batch geometry evaluation
def batch_evaluate_geometries(
    geometries: list[dict],
    s_values: np.ndarray,
) -> dict[str, np.ndarray]:
    """Evaluate multiple geometries at multiple s positions in batch."""
    # Group s values by which geometry they belong to
    results = {"x": np.zeros(len(s_values)), "y": np.zeros(len(s_values)), "hdg": np.zeros(len(s_values))}

    for i, geo in enumerate(geometries):
        s0 = geo["s"]
        s1 = s0 + geo["length"]
        mask = (s_values >= s0) & (s_values <= s1)

        if not np.any(mask):
            continue

        local_s = s_values[mask] - s0
        x, y, hdg = RoadGeometry._eval_segment(
            GeometrySegment(
                s_start=s0,
                x_start=geo["x"],
                y_start=geo["y"],
                hdg_start=geo["hdg"],
                length=geo["length"],
                type=geo["type"],
                params=geo.get("params", {}),
            ),
            local_s,
        )

        results["x"][mask] = x
        results["y"][mask] = y
        results["hdg"][mask] = hdg

    return results


from dataclasses import field