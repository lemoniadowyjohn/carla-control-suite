# ultimate_pipeline/visualization/map_diff.py

from __future__ import annotations
import math
import os
import xml.etree.ElementTree as ET
from typing import List, Tuple

import matplotlib.pyplot as plt

XY = Tuple[float, float]


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
    s = _safe_float(geom.get("s", "0"))
    x0 = _safe_float(geom.get("x", "0"))
    y0 = _safe_float(geom.get("y", "0"))
    hdg = _safe_float(geom.get("hdg", "0"))
    length = _safe_float(geom.get("length", "0"))

    arc = geom.find("arc")
    points: List[XY] = []

    if arc is None:
        # Straight line
        n = max(2, int(length / step))
        for i in range(n + 1):
            ds = length * (i / n)
            x = x0 + ds * math.cos(hdg)
            y = y0 + ds * math.sin(hdg)
            points.append((x, y))
    else:
        # Circular arc
        curvature = _safe_float(arc.get("curvature", "0"))
        if abs(curvature) < 1e-9:
            # fall back to straight
            return _sample_geometry(geom, step=step)

        R = 1.0 / curvature
        n = max(12, int(length / step))
        for i in range(n + 1):
            ds = length * (i / n)
            # arc length s = R * theta ⇒ theta = ds / R
            theta = ds / R
            # initial heading hdg is tangent at start
            # param angle φ = hdg + sign(curv)*π/2 + theta? For a rough view
            # We'll approximate by evolving along tangent rotated by curvature.
            # Better: integrate heading
            local_hdg = hdg + theta * curvature * abs(R)  # very rough but visually ok
            x = x0 + ds * math.cos(local_hdg)
            y = y0 + ds * math.sin(local_hdg)
            points.append((x, y))

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
    label_a: str,
    label_b: str,
    out_png: str,
    figsize=(6, 6)
) -> None:
    """
    Overlay two maps in a shared coordinate system.
    Great for seeing where geometry diverges.
    """
    polys_a = _load_polylines(xodr_a)
    polys_b = _load_polylines(xodr_b)

    plt.figure(figsize=figsize)

    for pts in polys_a:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        plt.plot(xs, ys, linewidth=0.7, alpha=0.8, label=label_a if '___added_a' not in locals() else None)
        ___added_a = True

    for pts in polys_b:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        plt.plot(xs, ys, linewidth=0.7, alpha=0.8, linestyle="--", label=label_b if '___added_b' not in locals() else None)
        ___added_b = True

    plt.legend()
    plt.title(f"{label_a} vs {label_b}")
    plt.gca().set_aspect("equal", adjustable="box")
    plt.grid(True, linewidth=0.3)
    plt.tight_layout()

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    plt.savefig(out_png, dpi=200)
    plt.close()
