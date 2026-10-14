"""
junction_connector_tangent_fit.py
=================================
CARLA-CLOSURE-17: GAP026 severe-angle junction connector closure (source stage).

Narrow repair that re-aims each severe-angle junction connector's contact-point
pose to the incoming road's source endpoint pose (position + tangent), while
preserving the far endpoint, by rewriting planView as a single paramPoly3
Hermite.

Why this closes the GAP026 angle:
  The gap026 oracle angle for a connection is
      ang = | src.heading - (tgt.heading + (0 if contactPoint==start else pi)) |
  where src is the incoming road's reference-line pose at s=length
  (``lane_center_oracle(..., at_start=False)`` returns hdg0) and tgt is the
  connecting road's reference-line pose at the contact point. Because
  ``lane_center_oracle`` returns the reference-line heading (lateral lane offset
  shifts position only), the angle depends *only* on the contact-point pose.
  Setting that pose to the incoming source pose drives ang -> 0 exactly, and
  (since the contact positions already coincide within ~1e-8 m) the lane-center
  distance collapses to the residual width/offset mismatch.

Scope / non-goals (deliberately minimal, no geometry framework):
  - Only roads with ``junction != -1`` are touched.
  - Only ``planView`` is rewritten: a single ``paramPoly3`` (normalized pRange).
    The road ``length`` attribute is preserved, so laneSection ``s`` offsets and
    elevations stay in range.
  - ``laneLink``/lane/road-link/junction definitions are never mutated.
  - Connectors whose contact-point angle is already within threshold are left
    untouched (previously passing controls stay passing).
  - ``contactPoint`` of ``start`` and ``end`` are both handled.

Usage:
  python -m ultimate_pipeline.topology.junction_connector_tangent_fit \\
      --input  path/to/input.xodr \\
      --output path/to/output.xodr \\
      [--angle-threshold 12.0]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.geometry.opendrive_geometry_kernel import (
    Pose,
    endpoint,
    pose_at_s,
)

# Geometry-authority gap026 threshold: 12 degrees (never raised).
DEFAULT_ANGLE_THRESHOLD_DEG = 12.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _wrap(angle: float) -> float:
    """Wrap to (-pi, pi]."""
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _norm_heading(angle: float) -> float:
    """Canonical heading for the hdg attribute.

    The pinned map-of-record stores headings in [0, 2*pi) (verified: 98879 of
    198233 geometries lie above pi), so wrap to that convention. For headings
    taken from existing geometry this is a no-op, which keeps preserved
    endpoint poses byte-exact; for contactPoint=end targets (source heading
    minus pi) it keeps the output in the same range as the input.
    """
    return float(angle) % (2.0 * math.pi)


def _is_connector_road(road: Optional[ET.Element]) -> bool:
    if road is None:
        return False
    return str(road.get("junction") or "").strip() not in ("", "-1")


def _sorted_geometries(road: ET.Element) -> List[ET.Element]:
    plan = road.find("./planView")
    if plan is None:
        return []
    geoms = list(plan.findall("./geometry"))
    geoms.sort(key=lambda g: _safe_float(g.get("s"), 0.0))
    return geoms


def _road_edge_pose(road: ET.Element, at_start: bool) -> Optional[Pose]:
    """Reference-line pose at a road edge using the geometry kernel.

    ``at_start=False`` returns the s=length endpoint -- this is exactly what the
    gap026 oracle uses for the incoming source heading.
    """
    geoms = _sorted_geometries(road)
    if not geoms:
        return None
    try:
        if at_start:
            return pose_at_s(geoms[0], 0.0)
        return endpoint(geoms[-1])
    except Exception:
        return None


def _hermite_param_poly3(
    start: Pose,
    end: Pose,
    tangent_magnitude: float,
) -> ET.Element:
    """Build a ``paramPoly3`` (normalized pRange) from ``start`` to ``end``.

    Local frame: origin at ``start``, x-axis along ``start.heading``. The cubic
    Hermite satisfies exactly: position/heading at p=0 -> start, at p=1 -> end.

    Returns the ``paramPoly3`` child element (coefficients as strings).
    """
    ca = math.cos(start.heading)
    sa = math.sin(start.heading)
    dx = float(end.x) - float(start.x)
    dy = float(end.y) - float(start.y)
    # Rotate world delta into local frame.
    p1x = ca * dx + sa * dy
    p1y = -sa * dx + ca * dy
    # End heading into local frame.
    end_heading_local = _wrap(float(end.heading) - float(start.heading))

    m = max(float(tangent_magnitude), 1e-6)
    # Start tangent along local +x: (m, 0). End tangent: m * (cos, sin).
    t0x, t0y = m, 0.0
    t1x = m * math.cos(end_heading_local)
    t1y = m * math.sin(end_heading_local)

    # Cubic Hermite coefficients (P0 = origin, T0 = start tangent).
    aU = 0.0
    bU = t0x
    cU = 3.0 * p1x - 2.0 * bU - t1x
    dU = -2.0 * p1x + bU + t1x
    aV = 0.0
    bV = t0y
    cV = 3.0 * p1y - bV - t1y
    dV = -2.0 * p1y + bV + t1y

    pp = ET.Element("paramPoly3")
    pp.set("aU", f"{aU:.12f}")
    pp.set("bU", f"{bU:.12f}")
    pp.set("cU", f"{cU:.12f}")
    pp.set("dU", f"{dU:.12f}")
    pp.set("aV", f"{aV:.12f}")
    pp.set("bV", f"{bV:.12f}")
    pp.set("cV", f"{cV:.12f}")
    pp.set("dV", f"{dV:.12f}")
    pp.set("pRange", "normalized")
    return pp


def _replace_planview_with_hermite(
    road: ET.Element,
    geom_start: Pose,
    geom_end: Pose,
    length: float,
) -> None:
    """Replace the road's planView with a single paramPoly3 geometry element."""
    plan = road.find("./planView")
    if plan is None:
        plan = ET.SubElement(road, "planView")
    for child in list(plan):
        plan.remove(child)

    geom = ET.SubElement(plan, "geometry")
    geom.set("s", "0.0")
    geom.set("x", f"{float(geom_start.x):.12f}")
    geom.set("y", f"{float(geom_start.y):.12f}")
    geom.set("hdg", f"{_norm_heading(float(geom_start.heading)):.12f}")
    geom.set("length", f"{float(length):.12f}")
    chord = math.hypot(
        float(geom_end.x) - float(geom_start.x),
        float(geom_end.y) - float(geom_start.y),
    )
    geom.append(_hermite_param_poly3(geom_start, geom_end, tangent_magnitude=chord))


def fit_junction_connector_tangents(
    root: ET.Element,
    angle_threshold_deg: float = DEFAULT_ANGLE_THRESHOLD_DEG,
) -> Dict[str, Any]:
    """Re-aim severe-angle junction connectors to their incoming source pose.

    Mutates ``root`` in place. Returns a report dict of counts.
    """
    roads: Dict[str, ET.Element] = {}
    for road in root.findall("./road"):
        rid = road.get("id")
        if rid is not None:
            roads[str(rid)] = road

    threshold_rad = math.radians(float(angle_threshold_deg))
    processed_connecting: set = set()

    connectors_examined = 0
    connectors_fitted = 0
    skipped_not_connector = 0
    skipped_missing = 0
    skipped_no_geometry = 0
    skipped_within_threshold = 0
    contact_start = 0
    contact_end = 0

    for junction in root.findall("./junction"):
        for connection in junction.findall("./connection"):
            incoming_id = str(connection.get("incomingRoad") or "")
            connecting_id = str(connection.get("connectingRoad") or "")
            incoming = roads.get(incoming_id)
            connecting = roads.get(connecting_id)

            if incoming is None or connecting is None:
                skipped_missing += 1
                continue
            if not _is_connector_road(connecting):
                skipped_not_connector += 1
                continue
            if connecting_id in processed_connecting:
                # A connecting road already fitted in another connection is left
                # as-is; its contact pose now matches that connection's source.
                continue

            geoms = _sorted_geometries(connecting)
            if not geoms:
                skipped_no_geometry += 1
                continue

            contact_point = str(connection.get("contactPoint") or "start").strip().lower()
            at_start = contact_point != "end"

            connectors_examined += 1

            # Incoming source pose at s=length (the gap026 oracle src).
            src = _road_edge_pose(incoming, at_start=False)
            if src is None:
                skipped_missing += 1
                continue

            # Contact pose of the connector (what the oracle samples as tgt).
            if at_start:
                contact_pose = pose_at_s(geoms[0], 0.0)
                far_pose = endpoint(geoms[-1])
            else:
                contact_pose = endpoint(geoms[-1])
                far_pose = pose_at_s(geoms[0], 0.0)
            if contact_pose is None or far_pose is None:
                skipped_no_geometry += 1
                continue

            # Gap026 angle for this connection (reference-line headings).
            heading_target = float(contact_pose.heading) + (0.0 if at_start else math.pi)
            angle = abs(_wrap(float(src.heading) - heading_target))
            if angle <= threshold_rad:
                skipped_within_threshold += 1
                continue

            # Source-backed contact target: incoming pose (heading flipped for
            # contactPoint=end so the oracle's +pi yields src.heading).
            contact_target_heading = float(src.heading) - (0.0 if at_start else math.pi)
            contact_target = Pose(float(src.x), float(src.y), contact_target_heading)

            # Geometry element runs start->end of planView (s=0 .. s=length).
            # contact is at s=0 when contactPoint=start, at s=length when end.
            if at_start:
                geom_start = contact_target
                geom_end = far_pose
                contact_start += 1
            else:
                geom_start = far_pose
                geom_end = contact_target
                contact_end += 1

            road_length = _safe_float(connecting.get("length"), 0.0)
            if road_length <= 0.0:
                road_length = sum(_safe_float(g.get("length"), 0.0) for g in geoms)
            if road_length <= 0.0:
                skipped_no_geometry += 1
                continue

            _replace_planview_with_hermite(connecting, geom_start, geom_end, road_length)
            processed_connecting.add(connecting_id)
            connectors_fitted += 1

    return {
        "connectors_examined": connectors_examined,
        "connectors_fitted": connectors_fitted,
        "contact_point_start": contact_start,
        "contact_point_end": contact_end,
        "skipped_not_connector": skipped_not_connector,
        "skipped_missing": skipped_missing,
        "skipped_no_geometry": skipped_no_geometry,
        "skipped_within_threshold": skipped_within_threshold,
        "angle_threshold_deg": float(angle_threshold_deg),
    }


def tangent_fit_enabled(default: bool = True) -> bool:
    """Env gate for the source-stage tangent fit (UP_JUNCTION_TANGENT_FIT)."""
    raw = os.environ.get("UP_JUNCTION_TANGENT_FIT")
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _report_path(output_path: Path) -> Path:
    if output_path.suffix:
        return output_path.with_suffix("").with_name(
            f"{output_path.with_suffix('').name}.tangent_fit_report.json"
        )
    return output_path.with_name(f"{output_path.name}.tangent_fit_report.json")


def run_tangent_fit(
    input_path: Path,
    output_path: Path,
    angle_threshold_deg: float = DEFAULT_ANGLE_THRESHOLD_DEG,
) -> Dict[str, Any]:
    input_path = Path(input_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    report_path = _report_path(output_path)

    tree = ET.parse(input_path)
    root = tree.getroot()
    report = fit_junction_connector_tangents(root, angle_threshold_deg=angle_threshold_deg)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="unicode", xml_declaration=True)

    full = {
        "input": str(input_path),
        "output": str(output_path),
        **report,
    }
    report_path.write_text(json.dumps(full, indent=2), encoding="utf-8")
    return full


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fit severe-angle junction connectors to their incoming source pose."
    )
    parser.add_argument("--input", required=True, help="Input XODR path.")
    parser.add_argument("--output", required=True, help="Output repaired XODR path.")
    parser.add_argument(
        "--angle-threshold",
        type=float,
        default=DEFAULT_ANGLE_THRESHOLD_DEG,
        help="Only fit connectors whose gap026 contact-point angle exceeds this (degrees).",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    report = run_tangent_fit(
        input_path=Path(args.input),
        output_path=Path(args.output),
        angle_threshold_deg=float(args.angle_threshold),
    )
    print("junction_connector_tangent_fit summary")
    print(f"  input: {report['input']}")
    print(f"  output: {report['output']}")
    print(f"  connectors_examined: {report['connectors_examined']}")
    print(f"  connectors_fitted: {report['connectors_fitted']}")
    print(f"  skipped_within_threshold: {report['skipped_within_threshold']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
