from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .exceptions import RoadRunnerContractError
from .models import SerializableContract


@dataclass(frozen=True)
class AlignmentMetrics(SerializableContract):
    scale: float
    translation_x: float
    translation_y: float
    heading_deg: float
    y_inverted: bool
    rmse: float
    point_count: int
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise RoadRunnerContractError("scale must be positive")
        if self.rmse < 0:
            raise RoadRunnerContractError("rmse must be non-negative")
        if self.point_count < 0:
            raise RoadRunnerContractError("point_count must be non-negative")
        if not math.isfinite(self.scale):
            raise RoadRunnerContractError("scale must be finite")
        if not math.isfinite(self.rmse):
            raise RoadRunnerContractError("rmse must be finite")


def _safe_float(value: str | float | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _extract_xodr_planview_points(root: ET.Element, max_per_road: int = 20) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for road in root.findall("road"):
        plan_view = road.find("planView")
        if plan_view is None:
            continue
        for geom in plan_view:
            x0 = _safe_float(geom.get("x"))
            y0 = _safe_float(geom.get("y"))
            hdg = _safe_float(geom.get("hdg"))
            length = max(0.0, _safe_float(geom.get("length")))
            samples = 3
            if length < 0.1:
                points.append((x0, y0))
                continue
            step = length / (samples - 1) if samples > 1 else 0.0
            for i in range(samples):
                t = i * step
                if geom.find("arc") is not None:
                    curvature = _safe_float(geom.find("arc").get("curvature"))
                    if abs(curvature) > 1e-12:
                        theta = hdg + curvature * t
                        xx = x0 + (math.sin(theta) - math.sin(hdg)) / curvature
                        yy = y0 - (math.cos(theta) - math.cos(hdg)) / curvature
                        points.append((xx, yy))
                        continue
                xx = x0 + t * math.cos(hdg)
                yy = y0 + t * math.sin(hdg)
                points.append((xx, yy))
            if len(points) >= max_per_road * len(root.findall("road")):
                break
    return points


def _compute_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    return sx / n, sy / n


def _compute_rmse(
    src_points: Sequence[tuple[float, float]],
    dst_points: Sequence[tuple[float, float]],
) -> float:
    if len(src_points) != len(dst_points) or not src_points:
        return -1.0
    total = 0.0
    for sp, dp in zip(src_points, dst_points):
        dx = sp[0] - dp[0]
        dy = sp[1] - dp[1]
        total += dx * dx + dy * dy
    return math.sqrt(total / len(src_points))


def _estimate_heading(
    src_points: Sequence[tuple[float, float]],
    dst_points: Sequence[tuple[float, float]],
) -> float:
    if len(src_points) < 2:
        return 0.0
    sx, sy = _compute_centroid(src_points)
    dx, dy = _compute_centroid(dst_points)
    angles: list[float] = []
    for sp, dp in zip(src_points, dst_points):
        v1 = (sp[0] - sx, sp[1] - sy)
        v2 = (dp[0] - dx, dp[1] - dy)
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        angle = math.atan2(cross, dot)
        angles.append(angle)
    if not angles:
        return 0.0
    return math.degrees(sum(angles) / len(angles))


def _estimate_scale(
    src_points: Sequence[tuple[float, float]],
    dst_points: Sequence[tuple[float, float]],
) -> float:
    if len(src_points) < 2:
        return 1.0
    sx, sy = _compute_centroid(src_points)
    dx, dy = _compute_centroid(dst_points)
    src_dists = [math.sqrt((p[0] - sx) ** 2 + (p[1] - sy) ** 2) for p in src_points]
    dst_dists = [math.sqrt((p[0] - dx) ** 2 + (p[1] - dy) ** 2) for p in dst_points]
    ratios = [d / s for s, d in zip(src_dists, dst_dists) if s > 1e-12]
    if not ratios:
        return 1.0
    return sum(ratios) / len(ratios)


def detect_y_inversion(
    src_points: Sequence[tuple[float, float]],
    dst_points: Sequence[tuple[float, float]],
) -> bool:
    if len(src_points) < 2:
        return False
    sx, sy = _compute_centroid(src_points)
    dx, dy = _compute_centroid(dst_points)
    inverted_count = 0
    for sp, dp in zip(src_points, dst_points):
        src_local_y = sp[1] - sy
        dst_local_y = dp[1] - dy
        if src_local_y * dst_local_y < 0:
            inverted_count += 1
    ratio = inverted_count / len(src_points)
    return ratio > 0.5


def compute_alignment(
    xodr_points: Sequence[tuple[float, float]],
    mesh_points: Sequence[tuple[float, float]],
    *,
    detect_y_inv: bool = True,
) -> AlignmentMetrics:
    if not xodr_points or not mesh_points:
        raise RoadRunnerContractError("both XODR and mesh point lists must be non-empty")
    min_len = min(len(xodr_points), len(mesh_points))
    if min_len < 2:
        raise RoadRunnerContractError("need at least 2 points for alignment estimation")
    xodr_slice = xodr_points[:min_len]
    mesh_slice = mesh_points[:min_len]
    cx, cy = _compute_centroid(xodr_slice)
    tx, ty = _compute_centroid(mesh_slice)
    translation_x = tx - cx
    translation_y = ty - cy
    heading = _estimate_heading(xodr_slice, mesh_slice)
    scale = _estimate_scale(xodr_slice, mesh_slice)
    rmse = _compute_rmse(xodr_slice, mesh_slice)
    y_inv = detect_y_inversion(xodr_slice, mesh_slice) if detect_y_inv else False
    notes: list[str] = []
    if y_inv:
        notes.append("y_inversion_detected")
    if abs(scale - 1.0) > 0.01:
        notes.append(f"non_uniform_scale_{scale:.4f}")
    if abs(heading) > 1.0:
        notes.append(f"rotation_{heading:.2f}_deg")
    return AlignmentMetrics(
        scale=scale,
        translation_x=round(translation_x, 6),
        translation_y=round(translation_y, 6),
        heading_deg=round(heading, 4),
        y_inverted=y_inv,
        rmse=round(rmse, 6),
        point_count=min_len,
        notes=tuple(notes),
    )


def extract_xodr_points(path: str | Path, max_per_road: int = 20) -> list[tuple[float, float]]:
    tree = ET.parse(str(path))
    root = tree.getroot()
    if root.tag != "OpenDRIVE":
        raise RoadRunnerContractError("not a valid OpenDRIVE XML")
    return _extract_xodr_planview_points(root, max_per_road=max_per_road)


def extract_mesh_bbox_points(bbox) -> list[tuple[float, float]]:
    return [
        (bbox.min_x, bbox.min_y),
        (bbox.max_x, bbox.min_y),
        (bbox.min_x, bbox.max_y),
        (bbox.max_x, bbox.max_y),
    ]


__all__ = [
    "AlignmentMetrics",
    "AlignmentMetrics",
    "compute_alignment",
    "detect_y_inversion",
    "extract_xodr_points",
    "extract_mesh_bbox_points",
]
