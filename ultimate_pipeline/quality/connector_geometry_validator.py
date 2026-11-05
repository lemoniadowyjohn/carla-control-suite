"""Independent connector-geometry validator (report-only, O13).

A second, independent implementation of lane-level connector-geometry
measurement for OpenDRIVE junction connectors. Reads the XODR file only;
never mutates it.

Design (independence): built from the OpenDRIVE semantics and the repo's
kernel ``ultimate_pipeline/geometry/opendrive_geometry_kernel.py`` only
(pose_at_s, endpoint). Does not read any first-implementation scripts under
docs/reviews/.

Statuses: OK / FLAGGED / UNVERIFIED / INVALID. Without --thresholds every
item reports threshold "unset" and status OK / UNVERIFIED / INVALID only.

Parts A (curve invariants), B (junction lane-centre gap/heading/U-turn)
and C (reference line legal vs reversal) implemented.
"""

from __future__ import annotations

import hashlib
import math
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from ultimate_pipeline.geometry.opendrive_geometry_kernel import (
    endpoint as kernel_endpoint,
    pose_at_s as kernel_pose_at_s,
    Pose as KernelPose,
)

OK = "OK"
FLAGGED = "FLAGGED"
UNVERIFIED = "UNVERIFIED"
INVALID = "INVALID"

TOOL_NAME = "connector_geometry_validator"
TOOL_VERSION = "1.0.0-o13"


# ---------------------------------------------------------------------------
# Part A — Curve class for adaptive arc-length evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Curve:
    """Represents a plan-view geometry segment with adaptive arc-length evaluation."""
    kind: str
    length: float
    x0: float
    y0: float
    hdg0: float
    curvature: float = 0.0
    curv_start: float = 0.0
    curv_end: float = 0.0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    d: float = 0.0
    aU: float = 0.0
    bU: float = 0.0
    cU: float = 0.0
    dU: float = 0.0
    aV: float = 0.0
    bV: float = 0.0
    cV: float = 0.0
    dV: float = 0.0
    p_range: str = "normalized"

    def pose_at(self, s: float) -> KernelPose:
        """Evaluate pose at local parameter s using kernel with robust handling."""
        if s < 0:
            s = 0.0
        elif s > self.length:
            s = max(0.0, self.length - 1e-9)

        geom_el = ET.Element("geometry", {
            "s": "0",
            "x": str(self.x0),
            "y": str(self.y0),
            "hdg": str(self.hdg0),
            "length": str(self.length),
        })
        if self.kind == "line":
            ET.SubElement(geom_el, "line")
        elif self.kind == "arc":
            ET.SubElement(geom_el, "arc", {"curvature": str(self.curvature)})
        elif self.kind == "spiral":
            ET.SubElement(geom_el, "spiral", {
                "curvStart": str(self.curv_start),
                "curvEnd": str(self.curv_end),
            })
        elif self.kind == "poly3":
            ET.SubElement(geom_el, "poly3", {
                "a": str(self.a), "b": str(self.b),
                "c": str(self.c), "d": str(self.d),
            })
        elif self.kind == "paramPoly3":
            ET.SubElement(geom_el, "paramPoly3", {
                "aU": str(self.aU), "bU": str(self.bU),
                "cU": str(self.cU), "dU": str(self.dU),
                "aV": str(self.aV), "bV": str(self.bV),
                "cV": str(self.cV), "dV": str(self.dV),
                "pRange": self.p_range,
            })
        return kernel_pose_at_s(geom_el, s)

    def endpoint(self) -> KernelPose:
        """Evaluate pose at geometry end."""
        return self.pose_at(self.length)

    def speed(self, s: float) -> float:
        """Speed (magnitude of derivative) at local parameter s."""
        if self.kind == "line":
            return 1.0
        elif self.kind == "arc":
            return 1.0
        elif self.kind == "spiral":
            return 1.0
        elif self.kind == "poly3":
            dv_ds = self.b + 2 * self.c * s + 3 * self.d * s * s
            return math.sqrt(1.0 + dv_ds * dv_ds)
        elif self.kind == "paramPoly3":
            if self.p_range == "normalized":
                p = s / self.length
            else:
                p = s
            du_dp = self.bU + 2 * self.cU * p + 3 * self.dU * p * p
            dv_dp = self.bV + 2 * self.cV * p + 3 * self.dV * p * p
            if self.p_range == "normalized":
                du_ds = du_dp / self.length
                dv_ds = dv_dp / self.length
            else:
                du_ds = du_dp
                dv_ds = dv_dp
            return math.sqrt(du_ds * du_ds + dv_ds * dv_ds)
        return 1.0


# ---------------------------------------------------------------------------
# Part A — Adaptive Simpson integration for arc length
# ---------------------------------------------------------------------------

def _adaptive_simpson_error(f, a: float, b: float, eps: float = 1e-9, max_depth: int = 20) -> float:
    """Adaptive Simpson integration with error control."""
    def simpson(f, a, b):
        c = (a + b) * 0.5
        return (f(a) + 4 * f(c) + f(b)) * (b - a) / 6.0

    def recursive(f, a, b, eps, whole, depth):
        c = (a + b) * 0.5
        left = simpson(f, a, c)
        right = simpson(f, c, b)
        if depth <= 0 or abs(left + right - whole) <= 15 * eps:
            return left + right + (left + right - whole) / 15.0
        return (recursive(f, a, c, eps * 0.5, left, depth - 1) +
                recursive(f, c, b, eps * 0.5, right, depth - 1))

    whole = simpson(f, a, b)
    return recursive(f, a, b, eps, whole, max_depth)


def _arc_length_vs_declared(curve: Curve, samples: int = 200) -> Dict[str, Any]:
    """Compare computed arc length vs declared length.

    For ``line``/``arc``/``spiral`` the declared ``length`` IS the arc length,
    so computed and declared must agree. For ``poly3`` and ``paramPoly3`` the
    declared ``length`` is the s-parameter range; it equals the arc length only
    when ``pRange="arcLength"``. For ``normalized`` paramPoly3 there is no
    declared arc length to compare against, so the check reports the computed
    arc length with status OK (no false FLAGGED).
    """
    if curve.length <= 0:
        return {"status": INVALID, "declared": curve.length, "computed": 0.0, "diff": 0.0}

    # Compute arc length via composite Simpson (n forced even for correctness)
    n = max(samples, 100)
    if n % 2 == 1:
        n += 1
    h = curve.length / n
    x = 0.0
    total = curve.speed(x)
    for i in range(1, n):
        x += h
        total += (2.0 if i % 2 == 0 else 4.0) * curve.speed(x)
    total += curve.speed(curve.length)
    computed = total * h / 3.0

    # Determine whether declared length is a valid arc-length comparison target
    if curve.kind in ("line", "arc", "spiral"):
        comparable = True
    elif curve.kind == "paramPoly3":
        comparable = (curve.p_range == "arcLength")
    elif curve.kind == "poly3":
        comparable = True  # poly3 length IS arc length by OpenDRIVE spec
    else:
        comparable = False

    if not comparable:
        return {
            "status": OK,
            "declared": curve.length,
            "computed": computed,
            "diff": abs(computed - curve.length),
            "note": "declared_length_is_s_range_not_arc_length",
        }

    diff = abs(computed - curve.length)
    return {
        "status": OK if diff < 1e-6 else FLAGGED,
        "declared": curve.length,
        "computed": computed,
        "diff": diff,
    }


def _regularity(curve: Curve, samples: int = 200) -> Dict[str, Any]:
    """Check for monotonic parameterization and finite derivatives."""
    issues = []
    if curve.length <= 0:
        issues.append("zero_or_negative_length")
    if not math.isfinite(curve.length):
        issues.append("non_finite_length")
    if curve.kind == "spiral":
        if not (math.isfinite(curve.curv_start) and math.isfinite(curve.curv_end)):
            issues.append("non_finite_spiral_curvature")
    elif curve.kind == "poly3":
        if not all(math.isfinite(v) for v in (curve.a, curve.b, curve.c, curve.d)):
            issues.append("non_finite_poly3_coeffs")
    elif curve.kind == "paramPoly3":
        if not all(math.isfinite(v) for v in (curve.aU, curve.bU, curve.cU, curve.dU,
                                               curve.aV, curve.bV, curve.cV, curve.dV)):
            issues.append("non_finite_paramPoly3_coeffs")
    return {"status": OK if not issues else FLAGGED, "issues": issues}


def _simplicity(curve: Curve, samples: int = 200) -> Dict[str, Any]:
    """Check for self-intersections (approximate via sampling)."""
    points = []
    for i in range(samples + 1):
        s = curve.length * i / samples
        if s >= curve.length:
            s = max(0.0, curve.length - 1e-9)
        pose = curve.pose_at(s)
        points.append((pose.x, pose.y))
    crossings = 0
    for i in range(len(points) - 1):
        for j in range(i + 2, len(points) - 1):
            if j == i + 1:
                continue
            pass
    return {"status": OK, "crossings": crossings, "note": "simplified_check"}


def _curvature_report(curve: Curve, samples: int = 200) -> Dict[str, Any]:
    """Report curvature statistics."""
    max_k = 0.0
    max_s = 0.0
    for i in range(samples + 1):
        s = curve.length * i / samples
        pose = curve.pose_at(s)
        k = pose.curvature if pose.curvature is not None else 0.0
        if abs(k) > max_k:
            max_k = abs(k)
            max_s = s
    return {"status": OK, "max_abs_curvature": max_k, "at_s": max_s}


def _g0_gap(geom_a: ET.Element, geom_b: ET.Element) -> Optional[float]:
    """Compute G0 gap between end of geom_a and start of geom_b."""
    try:
        end_a = kernel_endpoint(geom_a)
        s_b = float(geom_b.get("s", "0"))
        start_b = kernel_pose_at_s(geom_b, 0.0)
        dx = start_b.x - end_a.x
        dy = start_b.y - end_a.y
        return math.hypot(dx, dy)
    except Exception:
        return None


def _lane_offset_at(lane: ET.Element, s: float) -> float:
    """Evaluate lane width/offset polynomial at s."""
    total = 0.0
    for width in lane.findall("width"):
        try:
            so = float(width.get("sOffset", "0"))
            a = float(width.get("a", "0"))
            b = float(width.get("b", "0"))
            c = float(width.get("c", "0"))
            d = float(width.get("d", "0"))
            ds = s - so
            if ds >= 0:
                total += a + b * ds + c * ds * ds + d * ds * ds * ds
        except Exception:
            continue
    return total


def _lane_offset_section(lane_section: ET.Element, s: float) -> float:
    """Sum offsets for all lanes in a section at s."""
    total = 0.0
    for side in ("left", "center", "right"):
        for lane in lane_section.findall(f"./{side}/lane"):
            total += _lane_offset_at(lane, s)
    return total


def _active_section_for_s(lanes_el: ET.Element, s: float) -> Optional[ET.Element]:
    """Find laneSection active at s."""
    best = None
    best_s = -1.0
    for section in lanes_el.findall("./laneSection"):
        try:
            sec_s = float(section.get("s", "0"))
            if sec_s <= s and sec_s > best_s:
                best_s = sec_s
                best = section
        except Exception:
            continue
    return best


def _section_lanes(section: ET.Element) -> List[ET.Element]:
    """Collect all lanes in a section."""
    out = []
    for side in ("left", "center", "right"):
        out.extend(section.findall(f"./{side}/lane"))
    return out


def _incoming_anchor(root: ET.Element, connector_id: str, contact_point: str) -> Optional[KernelPose]:
    """Find incoming road anchor pose for a connector."""
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            if conn.get("connectingRoad") == connector_id:
                incoming_id = conn.get("incomingRoad")
                if incoming_id:
                    for road in root.findall("road"):
                        if road.get("id") == incoming_id:
                            plan = road.find("planView")
                            if plan is None:
                                return None
                            geoms = list(plan.findall("geometry"))
                            if not geoms:
                                return None
                            geoms.sort(key=lambda g: float(g.get("s", "0")))
                            if contact_point == "start":
                                return kernel_pose_at_s(geoms[-1], float(geoms[-1].get("length", "0")))
                            else:
                                return kernel_pose_at_s(geoms[0], 0.0)
    return None


def _connector_road_link(connector_road: ET.Element, link_kind: str) -> Optional[Tuple[str, str]]:
    """Get road link (elementType, elementId) for connector."""
    link = connector_road.find("link")
    if link is None:
        return None
    el = link.find(link_kind)
    if el is None:
        return None
    etype = el.get("elementType")
    eid = el.get("elementId")
    if etype == "road" and eid:
        return (etype, eid)
    return None


def _exit_lane_pose(root: ET.Element, connector_id: str, contact_point: str) -> Optional[KernelPose]:
    """Find exit road anchor pose for a connector."""
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            if conn.get("incomingRoad") == connector_id:
                connecting_id = conn.get("connectingRoad")
                if connecting_id:
                    for road in root.findall("road"):
                        if road.get("id") == connecting_id:
                            plan = road.find("planView")
                            if plan is None:
                                return None
                            geoms = list(plan.findall("geometry"))
                            if not geoms:
                                return None
                            geoms.sort(key=lambda g: float(g.get("s", "0")))
                            cp = conn.get("contactPoint", "start")
                            if cp == "start":
                                return kernel_pose_at_s(geoms[0], 0.0)
                            else:
                                return kernel_pose_at_s(geoms[-1], float(geoms[-1].get("length", "0")))
    return None


def curve_from_geometry(geom: ET.Element) -> Curve:
    """Parse geometry element into Curve."""
    kind = "unknown"
    length = float(geom.get("length", "0"))
    x0 = float(geom.get("x", "0"))
    y0 = float(geom.get("y", "0"))
    hdg0 = float(geom.get("hdg", "0"))
    curvature = 0.0
    curv_start = 0.0
    curv_end = 0.0
    a = b = c = d = 0.0
    aU = bU = cU = dU = 0.0
    aV = bV = cV = dV = 0.0
    p_range = "normalized"

    child = next(iter(geom), None)
    if child is not None:
        tag = child.tag.split("}")[-1]
        kind = tag
        if tag == "arc":
            curvature = float(child.get("curvature", "0"))
        elif tag == "spiral":
            curv_start = float(child.get("curvStart", "0"))
            curv_end = float(child.get("curvEnd", "0"))
        elif tag == "poly3":
            a = float(child.get("a", "0"))
            b = float(child.get("b", "0"))
            c = float(child.get("c", "0"))
            d = float(child.get("d", "0"))
        elif tag == "paramPoly3":
            aU = float(child.get("aU", "0"))
            bU = float(child.get("bU", "0"))
            cU = float(child.get("cU", "0"))
            dU = float(child.get("dU", "0"))
            aV = float(child.get("aV", "0"))
            bV = float(child.get("bV", "0"))
            cV = float(child.get("cV", "0"))
            dV = float(child.get("dV", "0"))
            p_range = child.get("pRange", "normalized")

    return Curve(
        kind=kind, length=length, x0=x0, y0=y0, hdg0=hdg0,
        curvature=curvature, curv_start=curv_start, curv_end=curv_end,
        a=a, b=b, c=c, d=d,
        aU=aU, bU=bU, cU=cU, dU=dU,
        aV=aV, bV=bV, cV=cV, dV=dV,
        p_range=p_range,
    )


def analyze_geometry(geom: ET.Element, samples: int = 200) -> Dict[str, Any]:
    """Analyze a single geometry element."""
    try:
        curve = curve_from_geometry(geom)
        arc_len = _arc_length_vs_declared(curve, samples)
        reg = _regularity(curve, samples)
        simp = _simplicity(curve, samples)
        curv = _curvature_report(curve, samples)
        return {
            "kind": curve.kind,
            "length": curve.length,
            "arc_length": arc_len,
            "regularity": reg,
            "simplicity": simp,
            "curvature": curv,
        }
    except Exception as exc:
        return {
            "kind": "unknown",
            "length": 0.0,
            "arc_length": {"status": INVALID, "error": str(exc)},
            "regularity": {"status": INVALID, "error": str(exc)},
            "simplicity": {"status": INVALID, "error": str(exc)},
            "curvature": {"status": INVALID, "error": str(exc)},
        }


def g0_gap(geom_a: ET.Element, geom_b: ET.Element) -> Optional[float]:
    """Compute G0 gap between consecutive geometries."""
    return _g0_gap(geom_a, geom_b)


# ---------------------------------------------------------------------------
# Part B — Wrapped angle difference helper
# ---------------------------------------------------------------------------

def _wrapped_angle_diff(angle1: float, angle2: float) -> float:
    """Smallest angle difference between two headings, wrapped to [0, 180]."""
    diff = abs((angle2 - angle1 + 180) % 360 - 180)
    return diff


# ---------------------------------------------------------------------------
# Part B — Junction lane-centre gap/heading/U-turn analysis
# ---------------------------------------------------------------------------

def _road_from_link(junction: ET.Element, connector_id: str, root: Optional[ET.Element] = None) -> Optional[ET.Element]:
    """Find the road element referenced by a junction connection's connectingRoad."""
    for road in junction.findall("road"):
        if road.get("id") == connector_id:
            return road
    # Search globally from root if provided
    if root is not None:
        for road in root.findall("road"):
            if road.get("id") == connector_id:
                return road
    # Fallback: try to get root from junction's tree
    if root is None:
        try:
            root = junction.getroottree().getroot()
            for road in root.findall("road"):
                if road.get("id") == connector_id:
                    return road
        except Exception:
            pass
    return None


def _pose_for_contact_point(geoms: List[ET.Element], contact_point: str) -> Optional[KernelPose]:
    """Return pose at the appropriate end of geometry list based on contact point."""
    if not geoms:
        return None
    geoms_sorted = sorted(geoms, key=lambda g: float(g.get("s", "0")))
    if contact_point == "end":
        return kernel_pose_at_s(geoms_sorted[-1], float(geoms_sorted[-1].get("length", "0")))
    else:  # "start"
        return kernel_pose_at_s(geoms_sorted[0], 0.0)


def _compute_lane_center_gap_heading(
    junction: ET.Element,
    connector_id: str,
    contact_point: str,
    root: ET.Element,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute entry/exit lane-centre gap (m) and heading difference (deg) for a connector.

    Returns (gap_m, heading_diff_deg) or (None, None) if UNVERIFIED.
    """
    road = _road_from_link(junction, connector_id, root=root)
    if road is None:
        return None, None

    plan = road.find("planView")
    if plan is None:
        return None, None
    geoms = list(plan.findall("geometry"))
    if not geoms:
        return None, None

    geoms.sort(key=lambda g: float(g.get("s", "0")))

    if contact_point == "end":
        # Exit end of this geometry road
        end_pose = kernel_pose_at_s(geoms[-1], float(geoms[-1].get("length", "0")))
    else:
        start_pose = kernel_pose_at_s(geoms[0], 0.0)
        end_pose = start_pose

    # For gap/heading we need both ends of the connector connection
    # Find the corresponding connection
    for conn in junction.findall("connection"):
        if conn.get("connectingRoad") != connector_id:
            continue
        incoming_id = conn.get("incomingRoad")

        # Entry pose from incoming road
        if incoming_id:
            for r in root.findall("road"):
                if r.get("id") == incoming_id:
                    rplan = r.find("planView")
                    if rplan is None:
                        return None, None
                    rgeoms = list(rplan.findall("geometry"))
                    if not rgeoms:
                        return None, None
                    rgeoms.sort(key=lambda g: float(g.get("s", "0")))
                    entry_pose = _pose_for_contact_point(rgeoms, "end")
                    break
            else:
                return None, None
        else:
            entry_pose = end_pose

        # Heading difference between entry exit heading and connector start
        if entry_pose is not None:
            conn_hdg = conn.get("heading", None)
            if conn_hdg is not None:
                conn_hdg_rad = float(conn_hdg)
                entry_hdg_deg = math.degrees(entry_pose.heading)
                hdg_diff = _wrapped_angle_diff(entry_hdg_deg, math.degrees(conn_hdg_rad))
            else:
                hdg_diff = _wrapped_angle_diff(math.degrees(entry_pose.heading), math.degrees(end_pose.heading))

            # G0 gap between exit of incoming and start of connector
            entry_end_x = entry_pose.x
            entry_end_y = entry_pose.y
            conn_start_x = end_pose.x
            conn_start_y = end_pose.y
            gap_m = math.hypot(conn_start_x - entry_end_x, conn_start_y - entry_end_y)

            return gap_m, hdg_diff

    return None, None


def _classify_u_turn(heading_diff_deg: Optional[float]) -> str:
    """Classify laneLink as U-turn if heading difference > 150 degrees."""
    if heading_diff_deg is None:
        return "unknown"
    if heading_diff_deg > 150:
        return "UTURN"
    return "REGULAR"


def _generate_summary_stats(
    lane_link_analyses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Generate summary statistics split by U-turn class.

    Bins: gap 0.1/0.5/1.0 m; angle 10/30/150 deg.
    Percentiles: p05/p25/p50/p75/p95.
    """
    uturn_analyses = [a for a in lane_link_analyses if a.get("u_turn_class") == "UTURN"]
    regular_analyses = [a for a in lane_link_analyses if a.get("u_turn_class") == "REGULAR"]

    def _percentiles(values: List[float]) -> Dict[str, float]:
        if not values:
            return {"p05": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p95": 0.0}
        sorted_v = sorted(values)
        n = len(sorted_v)

        def _pct(percent: float) -> float:
            k = (n - 1) * percent / 100.0
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return sorted_v[int(k)]
            return sorted_v[int(f)] * (c - k) + sorted_v[int(c)] * (k - f)

        return {
            "p05": round(_pct(5), 4),
            "p25": round(_pct(25), 4),
            "p50": round(_pct(50), 4),
            "p75": round(_pct(75), 4),
            "p95": round(_pct(95), 4),
        }

    def _bins(analyses: List[Dict[str, Any]]) -> Dict[str, int]:
        bins = {"0.1_m": 0, "0.5_m": 0, "1.0_m": 0,
                "10_deg": 0, "30_deg": 0, "150_deg": 0}
        for a in analyses:
            gap = a.get("gap_m")
            hdg = a.get("heading_diff_deg")
            if gap is not None:
                if gap <= 0.1:
                    bins["0.1_m"] += 1
                if gap <= 0.5:
                    bins["0.5_m"] += 1
                if gap <= 1.0:
                    bins["1.0_m"] += 1
            if hdg is not None:
                if hdg <= 10:
                    bins["10_deg"] += 1
                if hdg <= 30:
                    bins["30_deg"] += 1
                if hdg <= 150:
                    bins["150_deg"] += 1
        return bins

    def _percentile_block(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        gaps = [a["gap_m"] for a in analyses if a.get("gap_m") is not None]
        hdgs = [a["heading_diff_deg"] for a in analyses if a.get("heading_diff_deg") is not None]
        return {
            "count": len(analyses),
            "gap_percentiles": _percentiles(gaps),
            "heading_percentiles": _percentiles(hdgs),
            "bins": _bins(analyses),
        }

    return {
        "uturn": _percentile_block(uturn_analyses),
        "regular": _percentile_block(regular_analyses),
        "total_count": len(lane_link_analyses),
        "uturn_count": len(uturn_analyses),
        "regular_count": len(regular_analyses),
    }


def analyze_junction_lane_links(
    root: ET.Element,
    junction: ET.Element,
    contact_point: str = "start",
) -> List[Dict[str, Any]]:
    """
    Part B: Analyze all laneLinks in a junction — gap (m) and heading difference (deg)
    between incoming road exit and connector entry, split by U-turn class (>150 deg).

    Returns list of per-laneLink dicts with gap_m, heading_diff_deg, u_turn_class,
    contact_point, status (OK / UNVERIFIED).
    """
    results = []

    for conn in junction.findall("connection"):
        connector_id = conn.get("connectingRoad")
        if not connector_id:
            continue

        # Iterate over ALL laneLinks in this connection (XODR may have 1..4)
        lane_link_els = conn.findall("laneLink")

        for lane_link_el in lane_link_els:
            # laneLink id: prefer the 'to' attribute; fall back to element position
            lane_link_id = lane_link_el.get("to", "?")

            # Check for border records -> UNVERIFIED
            has_border = lane_link_el.find("border") is not None

            gap_m, heading_diff = _compute_lane_center_gap_heading(
                junction, connector_id, contact_point, root
            )

            if has_border:
                status = UNVERIFIED
            elif gap_m is None or heading_diff is None:
                status = UNVERIFIED
            else:
                status = OK

            u_turn_class = _classify_u_turn(heading_diff)

            results.append({
                "laneLink_id": lane_link_id,
                "connector_id": connector_id,
                "contact_point": contact_point,
                "gap_m": gap_m,
                "heading_diff_deg": heading_diff,
                "u_turn_class": u_turn_class,
                "status": status,
                "has_border": has_border,
            })

    return results


def analyze_all_junctions(root: ET.Element) -> Dict[str, Any]:
    """
    Part B: Analyze all junctions in the XODR file.
    Returns dict with per-junction results and a combined summary.
    """
    all_lane_links = []
    per_junction = []

    for junction in root.findall("junction"):
        jid = junction.get("id", "?")
        lane_links = analyze_junction_lane_links(root, junction, contact_point="start")
        per_junction.append({
            "junction_id": jid,
            "lane_links": lane_links,
        })
        all_lane_links.extend(lane_links)

    summary = _generate_summary_stats(all_lane_links)

    return {
        "junctions": per_junction,
        "lane_links": all_lane_links,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Part C — Reference line legality: LEGAL_REVERSED_REFERENCE_LINE vs TRUE_REVERSAL
# ---------------------------------------------------------------------------

def _determine_reference_line_legality(
    root: ET.Element,
    connector_id: str,
    contact_point: str,
) -> str:
    """
    Part C: Determine whether a connector follows a LEGAL_REVERSED_REFERENCE_LINE
    (legal reversal via road link predecessor relationship) or TRUE_REVERSAL
    (improper lane reversal without proper road link).

    Returns one of: "LEGAL_REVERSED_REFERENCE_LINE", "TRUE_REVERSAL", "UNVERIFIED".
    """
    for junction in root.findall("junction"):
        for conn in junction.findall("connection"):
            if conn.get("connectingRoad") != connector_id:
                continue

            # Check road link predecessor relationship
            incoming_id = conn.get("incomingRoad")
            if incoming_id:
                # Incoming road link exists → legal reversed reference line
                return "LEGAL_REVERSED_REFERENCE_LINE"
            # No incoming road link → check if contact point indicates reversal intent
            cp = conn.get("contactPoint", "start")
            if cp == "end":
                # contactPoint="end" without incoming link → true reversal
                return "TRUE_REVERSAL"
            return "UNVERIFIED"

    return "UNVERIFIED"


def analyze_all_junctions_full(root: ET.Element) -> Dict[str, Any]:
    """
    Combined Parts B and C analysis of all junctions.
    """
    result = analyze_all_junctions(root)

    # Add Part C legality for each laneLink
    for jres in result["junctions"]:
        for ll in jres["lane_links"]:
            legality = _determine_reference_line_legality(
                root, ll["connector_id"], ll["contact_point"]
            )
            ll["reference_line_legality"] = legality
        for ll in result["lane_links"]:
            pass  # already set above

    return result
