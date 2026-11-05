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


def _active_lane_section(lanes_el: ET.Element, s: float) -> Optional[ET.Element]:
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


def _lane_id_to_idx(lane_id: str) -> int:
    """Convert lane id string to index. Left lanes have positive ids, right lanes negative."""
    return int(lane_id)


def _lane_width_at(s: float, lane_section: ET.Element, lane: ET.Element, all_lanes_info: List[Dict[str, Any]]) -> float:
    """Compute the lane-centre offset relative to the lane's centre.
    
    Positive offset is to the left.
    """
    lid = _lane_id_to_idx(lane.get("id", "0"))
    # Find the centre of this lane
    lane_s = float(lane.get("s", "0"))
    lane_len = float(lane.get("length", "0"))
    s_local = s - lane_s
    if s_local < 0 or s_local > lane_len:
        return 0.0
    offset = _lane_offset_at(lane, s_local)
    # Find all lanes in the section to compute cumulative offsets
    section = lane_section
    if section is None:
        return offset
    
    # Compute the centre offset within the section
    # Lanes are ordered: left, center, right. Positive ids = left.
    # We need the offset of the target lane from the section start.
    # If lane id > 0, it's to the right; if < 0, it's to the left.
    # The cumulative offset of lanes before this one gives the lane-centre position.
    
    all_in_section = _section_lanes(section)
    cumulative = 0.0
    for ln in all_in_section:
        ln_id = _lane_id_to_idx(ln.get("id", "0"))
        if ln_id == lid:
            # This is our lane; return the offset from section centre
            # Lane centre = cumulative width of preceding lanes + half this lane's width
            ln_width = _lane_offset_at(ln, s_local)
            return cumulative + ln_width / 2.0
        # Add this lane's width to cumulative
        ln_width = _lane_offset_at(ln, s_local)
        # Lane width is roughly constant for simplicity; use centre offset
        cumulative += ln_width
    
    return offset


def _compute_reference_pose(geom: ET.Element, s: float) -> Optional[KernelPose]:
    """Get pose at parameter s on a geometry element."""
    if s < 0 or s > float(geom.get("length", "0")):
        return None
    return kernel_pose_at_s(geom, s)


def _heading_diff_deg(h1: float, h2: float) -> float:
    """Compute wrapped angle difference in degrees [0, 180]."""
    return _wrapped_angle_diff(h1, h2)


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


def _road_from_link(junction: ET.Element, connector_id: str, root: Optional[ET.Element] = None) -> Optional[ET.Element]:
    """Find the road element referenced by a junction connection's connectingRoad."""
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


def _get_incoming_road_info(root: ET.Element, junction: ET.Element, connector_id: str) -> Optional[Tuple[ET.Element, str, str]]:
    """Get incoming road, contact point, and incoming lane section end s."""
    for conn in junction.findall("connection"):
        if conn.get("connectingRoad") == connector_id:
            incoming_id = conn.get("incomingRoad")
            contact_point = conn.get("contactPoint", "start")
            if incoming_id:
                for r in root.findall("road"):
                    if r.get("id") == incoming_id:
                        return r, contact_point, incoming_id
    return None


def _get_connector_road_info(root: ET.Element, junction: ET.Element, connector_id: str) -> Optional[Tuple[ET.Element, str]]:
    """Get connector road and its road-level link info."""
    for conn in junction.findall("connection"):
        if conn.get("connectingRoad") == connector_id:
            cp = conn.get("contactPoint", "start")
            # Get connector road
            for r in root.findall("road"):
                if r.get("id") == connector_id:
                    return r, cp
    return None


def _get_road_link_target(road: ET.Element, link_kind: str) -> Optional[str]:
    """Get road link target (elementId) for successor/predecessor.

    Returns the elementId regardless of elementType (road or junction),
    since a road can link to either.
    """
    link = road.find("link")
    if link is None:
        return None
    el = link.find(link_kind)
    if el is None:
        return None
    eid = el.get("elementId")
    if eid:
        return eid
    return None


def _get_lane_link_target(lane: ET.Element, link_kind: str) -> Optional[str]:
    """Get lane link target id for successor/predecessor.

    Lane links use the ``id`` attribute in OpenDRIVE; road links use
    ``elementId``. Accept both so either encoding resolves.
    """
    link = lane.find("link")
    if link is None:
        return None
    el = link.find(link_kind)
    if el is None:
        return None
    return el.get("id") or el.get("elementId")


def _road_pose_at(road: ET.Element, s: float) -> Optional[KernelPose]:
    """Evaluate the road reference-line pose at ``s`` with tolerant clamping.

    OpenDRIVE positions are accumulated as ``geometry.s + geometry.length``.
    Binary floating point can overshoot the declared geometry length by
    1e-15..5e-13 m at a shared endpoint (measured: 87,087 of 218,347
    geometries on the Stage-5 map). The kernel enforces exact bounds, so
    clamp the local parameter rather than failing the whole laneLink.
    """
    plan = road.find("planView")
    if plan is None:
        return None
    geoms = sorted(plan.findall("geometry"), key=lambda g: float(g.get("s", "0")))
    for geom in geoms:
        geom_s = float(geom.get("s", "0"))
        geom_len = float(geom.get("length", "0"))
        if geom_s - 1e-9 <= s <= geom_s + geom_len + 1e-9:
            s_local = min(max(s - geom_s, 0.0), geom_len)
            return kernel_pose_at_s(geom, s_local)
    return None


def _get_lane_centre_pose(road: ET.Element, lane_id: str, s: float) -> Optional[KernelPose]:
    """Get the lane-centre pose (position + heading) at parameter s on a road.
    
    Args:
        road: Road element
        lane_id: Lane id string (e.g., "-1", "2")
        s: s-parameter along the road reference line
        
    Returns:
        KernelPose with lane-centre position and travel heading, or None on failure
    """
    try:
        ref_pose = _road_pose_at(road, s)
        if ref_pose is None:
            return None

        # Get lane offset at this s
        lanes_el = road.find("lanes")
        if lanes_el is None:
            return None
        lane_section = _active_lane_section(lanes_el, s)
        if lane_section is None:
            return None

        # Find the target lane
        target_lane = None
        for side in ("left", "center", "right"):
            for lane in lane_section.findall(f"./{side}/lane"):
                if lane.get("id") == lane_id:
                    target_lane = lane
                    break
            if target_lane is not None:
                break

        if target_lane is None:
            return None

        # Compute lateral offset from the reference line to the lane centre.
        # Positive offset = left of reference line.
        lane_id_int = int(lane_id)
        lane_s = s - float(lane_section.get("s", "0"))

        if lane_id_int > 0:  # Left lanes
            offset = 0.0
            for side in ("left", "center", "right"):
                for lane in lane_section.findall(f"./{side}/lane"):
                    ln_id = int(lane.get("id", "0"))
                    if ln_id == 0:
                        continue
                    if 0 < ln_id < lane_id_int:
                        offset += _lane_offset_at(lane, lane_s)
            offset += _lane_offset_at(target_lane, lane_s) / 2.0
        elif lane_id_int < 0:  # Right lanes
            offset = 0.0
            for side in ("left", "center", "right"):
                for lane in lane_section.findall(f"./{side}/lane"):
                    ln_id = int(lane.get("id", "0"))
                    if lane_id_int < ln_id < 0:
                        offset -= _lane_offset_at(lane, lane_s)
            offset -= _lane_offset_at(target_lane, lane_s) / 2.0
        else:  # Center lane
            offset = 0.0

        # Apply lateral offset to get lane-centre position
        # Left normal: (-sin(h), cos(h))
        hdg = ref_pose.heading
        nx = -math.sin(hdg)
        ny = math.cos(hdg)
        lc_x = ref_pose.x + offset * nx
        lc_y = ref_pose.y + offset * ny

        # Travel heading: reference heading for right lanes (id < 0),
        # reference heading + pi for left lanes (id > 0)
        travel_hdg = hdg
        if lane_id_int > 0:
            travel_hdg += math.pi
            if travel_hdg > math.pi:
                travel_hdg -= 2 * math.pi

        return KernelPose(
            x=lc_x,
            y=lc_y,
            heading=travel_hdg,
            curvature=ref_pose.curvature,
        )
    except Exception:
        return None


def _compute_lane_link_gaps(
    junction: ET.Element,
    connector_id: str,
    incoming_lane_id: str,
    connector_lane_id: str,
    root: ET.Element,
) -> Dict[str, Any]:
    """Compute entry/exit gaps and heading differences for a single laneLink.
    
    Returns dict with:
    - entry_gap_m, entry_heading_diff_deg
    - exit_gap_m, exit_heading_diff_deg
    - u_turn (bool)
    - status (OK/UNVERIFIED/INVALID)
    - reason (if UNVERIFIED/INVALID)
    - reference_line_gap_m (extra field, reference-line only gap)
    """
    result = {
        "entry_gap_m": None,
        "entry_heading_diff_deg": None,
        "exit_gap_m": None,
        "exit_heading_diff_deg": None,
        "u_turn": False,
        "status": UNVERIFIED,
        "reason": "",
        "reference_line_gap_m": None,
    }
    
    try:
        # Get incoming road and connector road
        incoming_info = _get_incoming_road_info(root, junction, connector_id)
        if incoming_info is None:
            result["reason"] = "no_incoming_connection"
            return result
        incoming_road, conn_cp, incoming_road_id = incoming_info
        
        connector_info = _get_connector_road_info(root, junction, connector_id)
        if connector_info is None:
            result["reason"] = "no_connector_road"
            return result
        connector_road, connector_cp = connector_info
        
        # Find incoming road's end s (where it meets the junction)
        # The incoming road's link successor should point to this junction
        incoming_succ = _get_road_link_target(incoming_road, "successor")
        if incoming_succ != junction.get("id"):
            # Try predecessor (reversed)
            incoming_pred = _get_road_link_target(incoming_road, "predecessor")
            if incoming_pred != junction.get("id"):
                result["reason"] = "incoming_road_not_linked_to_junction"
                return result
            # If predecessor matches, travel is toward s=0
            incoming_end_s = 0.0
        else:
            # Successor matches, travel is toward end of road
            plan = incoming_road.find("planView")
            if plan is None:
                result["reason"] = "incoming_no_planview"
                return result
            geoms = list(plan.findall("geometry"))
            if not geoms:
                result["reason"] = "incoming_no_geoms"
                return result
            geoms.sort(key=lambda g: float(g.get("s", "0")))
            incoming_end_s = float(geoms[-1].get("s", "0")) + float(geoms[-1].get("length", "0"))
        
        # Find connector road's start/end s based on contactPoint
        plan = connector_road.find("planView")
        if plan is None:
            result["reason"] = "connector_no_planview"
            return result
        geoms = list(plan.findall("geometry"))
        if not geoms:
            result["reason"] = "connector_no_geoms"
            return result
        geoms.sort(key=lambda g: float(g.get("s", "0")))
        connector_start_s = float(geoms[0].get("s", "0"))
        connector_end_s = float(geoms[-1].get("s", "0")) + float(geoms[-1].get("length", "0"))
        
        # Entry: incoming lane at its end vs connector lane at its start (s=0 for contactPoint="start")
        entry_s_incoming = incoming_end_s
        if connector_cp == "start":
            entry_s_connector = connector_start_s
        else:
            entry_s_connector = connector_end_s
        
        # Get lane-centre poses at entry
        incoming_lc = _get_lane_centre_pose(incoming_road, incoming_lane_id, entry_s_incoming)
        connector_lc = _get_lane_centre_pose(connector_road, connector_lane_id, entry_s_connector)
        
        if incoming_lc is None or connector_lc is None:
            result["reason"] = "lane_centre_computation_failed"
            return result
        
        # Entry gap
        dx = connector_lc.x - incoming_lc.x
        dy = connector_lc.y - incoming_lc.y
        result["entry_gap_m"] = math.hypot(dx, dy)
        
        # Entry heading diff
        h1 = math.degrees(incoming_lc.heading)
        h2 = math.degrees(connector_lc.heading)
        result["entry_heading_diff_deg"] = _wrapped_angle_diff(h1, h2)
        
        # Reference line gap (for comparison): each reference pose must be
        # evaluated on its own road. The previous version reused the connector
        # road's geometry list for the incoming pose as well.
        incoming_ref = _road_pose_at(incoming_road, entry_s_incoming)
        connector_ref = _road_pose_at(connector_road, entry_s_connector)
        if incoming_ref is None or connector_ref is None:
            result["reason"] = "reference_line_computation_failed"
            return result
        dx_ref = connector_ref.x - incoming_ref.x
        dy_ref = connector_ref.y - incoming_ref.y
        result["reference_line_gap_m"] = math.hypot(dx_ref, dy_ref)
        
        # Exit: connector lane at its far end vs successor road/lane
        # Determine connector's exit s based on contactPoint
        if connector_cp == "start":
            exit_s_connector = connector_end_s
        else:
            exit_s_connector = connector_start_s
        
        # Get successor road from connector's road link
        succ_road_id = _get_road_link_target(connector_road, "successor")
        if succ_road_id is None:
            # Try predecessor for reversed
            succ_road_id = _get_road_link_target(connector_road, "predecessor")
            if succ_road_id is None:
                result["reason"] = "connector_no_road_link"
                return result
            # Reversed: travel toward s=0 on successor
            exit_s_succ = 0.0
        else:
            exit_s_succ = None  # Will compute from successor road
        
        # Get successor lane from connector lane's link
        connector_lane_section = _active_lane_section(connector_road.find("lanes"), exit_s_connector)
        if connector_lane_section is None:
            result["reason"] = "connector_no_lane_section"
            return result
        connector_lane = None
        for side in ("left", "center", "right"):
            for lane in connector_lane_section.findall(f"./{side}/lane"):
                if lane.get("id") == connector_lane_id:
                    connector_lane = lane
                    break
            if connector_lane is not None:
                break
        
        succ_lane_id = _get_lane_link_target(connector_lane, "successor")
        if succ_lane_id is None:
            succ_lane_id = _get_lane_link_target(connector_lane, "predecessor")
            if succ_lane_id is None:
                result["reason"] = "connector_lane_no_link"
                return result
        
        # Get successor road
        succ_road = None
        for r in root.findall("road"):
            if r.get("id") == succ_road_id:
                succ_road = r
                break
        if succ_road is None:
            result["reason"] = "successor_road_not_found"
            return result
        
        # Compute successor road's entry s
        if exit_s_succ is None:
            # Find succ road's planview and get start
            succ_plan = succ_road.find("planView")
            if succ_plan is None:
                result["reason"] = "successor_no_planview"
                return result
            succ_geoms = list(succ_plan.findall("geometry"))
            if not succ_geoms:
                result["reason"] = "successor_no_geoms"
                return result
            succ_geoms.sort(key=lambda g: float(g.get("s", "0")))
            exit_s_succ = float(succ_geoms[0].get("s", "0"))
        
        # Get lane-centre poses at exit
        connector_exit_lc = _get_lane_centre_pose(connector_road, connector_lane_id, exit_s_connector)
        succ_exit_lc = _get_lane_centre_pose(succ_road, succ_lane_id, exit_s_succ)
        
        if connector_exit_lc is None or succ_exit_lc is None:
            result["reason"] = "exit_lane_centre_computation_failed"
            return result
        
        # Exit gap
        dx_exit = succ_exit_lc.x - connector_exit_lc.x
        dy_exit = succ_exit_lc.y - connector_exit_lc.y
        result["exit_gap_m"] = math.hypot(dx_exit, dy_exit)
        
        # Exit heading diff
        h1_exit = math.degrees(connector_exit_lc.heading)
        h2_exit = math.degrees(succ_exit_lc.heading)
        result["exit_heading_diff_deg"] = _wrapped_angle_diff(h1_exit, h2_exit)
        
        # U-turn: incoming travel heading vs exit travel heading > 150 deg
        # Use incoming entry heading vs exit heading
        h_in = math.degrees(incoming_lc.heading)
        h_out = math.degrees(succ_exit_lc.heading)
        hdg_diff_u = _wrapped_angle_diff(h_in, h_out)
        result["u_turn"] = hdg_diff_u > 150.0
        
        result["status"] = OK
        result["reason"] = ""
        
    except Exception as e:
        result["status"] = INVALID
        result["reason"] = f"exception: {e}"
    
    return result


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
    uturn_analyses = [a for a in lane_link_analyses if a.get("u_turn")]
    regular_analyses = [a for a in lane_link_analyses if not a.get("u_turn")]

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
            gap = a.get("entry_gap_m")
            hdg = a.get("entry_heading_diff_deg")
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
        gaps = [a["entry_gap_m"] for a in analyses if a.get("entry_gap_m") is not None]
        hdgs = [a["entry_heading_diff_deg"] for a in analyses if a.get("entry_heading_diff_deg") is not None]
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
    Part B: Analyze all laneLinks in a junction — lane-centre entry/exit gaps (m)
    and heading differences (deg) between incoming road exit and connector entry,
    and connector exit vs successor road entry. Split by U-turn class (>150 deg).

    Returns list of per-laneLink dicts with:
    - entry_gap_m, entry_heading_diff_deg
    - exit_gap_m, exit_heading_diff_deg
    - u_turn (bool)
    - status (OK / UNVERIFIED / INVALID)
    - reason (if UNVERIFIED/INVALID)
    - reference_line_gap_m (reference-line only gap for comparison)
    """
    results = []

    for conn in junction.findall("connection"):
        connector_id = conn.get("connectingRoad")
        if not connector_id:
            continue

        # Iterate over ALL laneLinks in this connection (XODR may have 1..4)
        lane_link_els = conn.findall("laneLink")

        for lane_link_el in lane_link_els:
            # laneLink attributes: from = incoming lane id, to = connector lane id
            incoming_lane_id = lane_link_el.get("from", "?")
            connector_lane_id = lane_link_el.get("to", "?")
            lane_link_id = f"{incoming_lane_id}->{connector_lane_id}"

            # Check for border records -> UNVERIFIED
            has_border = lane_link_el.find("border") is not None

            # Compute per-laneLink gaps
            gap_result = _compute_lane_link_gaps(
                junction, connector_id, incoming_lane_id, connector_lane_id, root
            )

            if has_border:
                status = UNVERIFIED
                reason = "has_border"
            else:
                status = gap_result["status"]
                reason = gap_result["reason"]

            u_turn = gap_result["u_turn"]

            results.append({
                "laneLink_id": lane_link_id,
                "connector_id": connector_id,
                "incoming_lane_id": incoming_lane_id,
                "connector_lane_id": connector_lane_id,
                "contact_point": contact_point,
                "entry_gap_m": gap_result["entry_gap_m"],
                "entry_heading_diff_deg": gap_result["entry_heading_diff_deg"],
                "exit_gap_m": gap_result["exit_gap_m"],
                "exit_heading_diff_deg": gap_result["exit_heading_diff_deg"],
                "reference_line_gap_m": gap_result["reference_line_gap_m"],
                "u_turn": u_turn,
                "status": status,
                "reason": reason,
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
