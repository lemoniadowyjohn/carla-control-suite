# ultimate_pipeline/visualization/map_diff.py

from __future__ import annotations
import math
import os
import xml.etree.ElementTree as ET
from typing import List, Tuple

import matplotlib.pyplot as plt

from opendrive_geometry.evaluator import LineArcEvaluator, EvaluationPolicy, RangePolicy
from opendrive_geometry.model import GeometrySegment

XY = Tuple[float, float]

_MAP_DIFF_EVALUATOR = LineArcEvaluator(
    EvaluationPolicy(
        range_policy=RangePolicy.CLAMP,
    )
)


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _sample_geometry(geom: ET.Element, step: float = 5.0) -> List[XY]:
    """
    Sample a <geometry> element into a list of (x, y) points.

    Supports:
      - straight line (no child)
      - <arc curvature="...">
    """
    x0 = _safe_float(geom.get("x", "0"))
    y0 = _safe_float(geom.get("y", "0"))
    hdg = _safe_float(geom.get("hdg", "0"))
    length = _safe_float(geom.get("length", "0"))

    arc = geom.find("arc")
    points: List[XY] = []

    if arc is None:
        # Straight line
        seg = GeometrySegment(s0=0.0, length=length, x0=x0, y0=y0, hdg0=hdg, geometry_type="line")
        n = max(2, int(length / step))
        for i in range(n + 1):
            p = _MAP_DIFF_EVALUATOR.pose_at(seg, length * (i / n))
            points.append((p.x, p.y))
    else:
        # Circular arc
        curvature = _safe_float(arc.get("curvature", "0"))
        seg = GeometrySegment(s0=0.0, length=length, x0=x0, y0=y0, hdg0=hdg, geometry_type="arc")
        if abs(curvature) < 1e-12:
            n = max(2, int(length / step))
            for i in range(n + 1):
                p = _MAP_DIFF_EVALUATOR.pose_at(seg, length * (i / n), curvature=curvature)
                points.append((p.x, p.y))
            return points

        n = max(12, int(length / step))
        for i in range(n + 1):
            p = _MAP_DIFF_EVALUATOR.pose_at(seg, length * (i / n), curvature=curvature)
            points.append((p.x, p.y))

    return points


def _extract_road_polylines(root: ET.Element) -> List[List[XY]]:
    """
    Convert all roads into polylines by sampling planView geometries.
    """
    polylines: List[List[XY]] = []
    for road in root.findall("road"):
        plan = road.find("planView")
        if plan is None:
            continue
        segs = plan.findall("geometry")
        if not segs:
            continue

        road_pts: List[XY] = []
        for g in segs:
            pts = _sample_geometry(g, step=5.0)
            if not pts:
                continue
            if not road_pts:
                road_pts.extend(pts)
            else:
                # avoid duplicating the first point
                road_pts.extend(pts[1:])
        if road_pts:
            polylines.append(road_pts)

    return polylines


def _load_polylines(xodr_path: str) -> List[List[XY]]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    return _extract_road_polylines(root)


def plot_maps_side_by_side(
    xodr_a: str,
    xodr_b: str,
    label_a: str,
    label_b: str,
    out_png: str,
    figsize=(10, 5)
) -> None:
    """
    Render two maps side-by-side (manual vs auto).
    """
    polys_a = _load_polylines(xodr_a)
    polys_b = _load_polylines(xodr_b)

    fig, axes = plt.subplots(1, 2, figsize=figsize, sharex=False, sharey=False)

    for pts in polys_a:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        axes[0].plot(xs, ys, linewidth=0.8)
    axes[0].set_title(label_a)
    axes[0].set_aspect("equal", adjustable="box")

    for pts in polys_b:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        axes[1].plot(xs, ys, linewidth=0.8)
    axes[1].set_title(label_b)
    axes[1].set_aspect("equal", adjustable="box")

    for ax in axes:
        ax.grid(True, linewidth=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()


def overlay_maps(
    xodr_a: str,
    xodr_b: str,
    label_a: str = "Manual",
    label_b: str = "Auto",
    out_png: str = "overlay.png",
    figsize=(8, 8),
    color_a: str = "#1f77b4",  # Blue for manual
    color_b: str = "#d62728",  # Red for auto (aligned)
    linewidth_a: float = 1.0,
    linewidth_b: float = 0.7,
    alpha_a: float = 0.9,
    alpha_b: float = 0.7,
) -> str:
    """
    Overlay two maps in a shared coordinate system using contrasting colors.
    Great for seeing where geometry diverges.

    Args:
        xodr_a: Path to first XODR (typically manual/reference)
        xodr_b: Path to second XODR (typically auto/aligned)
        label_a: Label for first map (default: "Manual")
        label_b: Label for second map (default: "Auto")
        out_png: Output PNG path
        figsize: Figure size tuple
        color_a: Color for first map (default: blue)
        color_b: Color for second map (default: red)
        linewidth_a: Line width for first map
        linewidth_b: Line width for second map
        alpha_a: Alpha for first map
        alpha_b: Alpha for second map

    Returns:
        Path to saved PNG file
    """
    polys_a = _load_polylines(xodr_a)
    polys_b = _load_polylines(xodr_b)

    plt.figure(figsize=figsize)

    first_a = True
    for pts in polys_a:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        plt.plot(
            xs, ys,
            linewidth=linewidth_a,
            alpha=alpha_a,
            color=color_a,
            label=label_a if first_a else None,
            solid_capstyle='round',
        )
        first_a = False

    first_b = True
    for pts in polys_b:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        plt.plot(
            xs, ys,
            linewidth=linewidth_b,
            alpha=alpha_b,
            color=color_b,
            linestyle="--",
            label=label_b if first_b else None,
            solid_capstyle='round',
        )
        first_b = False

    plt.legend(loc='upper right', fontsize=9)
    plt.title(f"{label_a} vs {label_b}", fontsize=11)
    plt.xlabel("X (m)")
    plt.ylabel("Y (m)")
    plt.gca().set_aspect("equal", adjustable="box")
    plt.grid(True, linewidth=0.3, alpha=0.5)
    plt.tight_layout()

    # Ensure parent directory exists
    out_dir = os.path.dirname(out_png)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(out_png, dpi=200, bbox_inches='tight')
    plt.close()

    return out_png


# ---------------------------------------------------------------------------
# Compatibility wrapper (some tools expect a MapDiff class)
# ---------------------------------------------------------------------------

class MapDiff:
    """Thin OO wrapper around the functional map diff helpers.

    Existing scripts in this repo historically used:

        from ultimate_pipeline.visualization.map_diff import MapDiff
        MapDiff.compare(a, b, out_prefix="...")

    The original implementation evolved into standalone functions; this wrapper
    preserves the old API without changing the plotting code.
    """

    @staticmethod
    def compare(
        xodr_a: str,
        xodr_b: str,
        *,
        out_prefix: str = "mapdiff",
        out_dir: str = ".",
        label_a: str = "Manual",
        label_b: str = "Auto",
    ) -> str:
        """Generate an overlay diff PNG and return its path."""
        out_png = os.path.join(out_dir, f"{out_prefix}_overlay.png")
        overlay_maps(
            xodr_a,
            xodr_b,
            label_a=label_a,
            label_b=label_b,
            out_png=out_png,
        )
        return out_png

