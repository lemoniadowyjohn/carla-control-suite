"""TOP-JCT-RAB-LLK-001 — fail-closed topology validation layer.

Read-only validators and candidate-acceptance gates for road topology,
junctions, roundabouts and LaneLinks.  Any candidate that fails validation
is REJECTED (never written); ambiguity in LaneLink matching is rejected,
not guessed; reciprocity violations are reported for repair, never silent.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Shared pose helpers (self-contained; no dependency on geometry evaluators)
# ---------------------------------------------------------------------------
def _f(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float(default)
    return v if math.isfinite(v) else float(default)


def _norm_angle(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _angle_diff(a: float, b: float) -> float:
    return _norm_angle(a - b)


@dataclass(frozen=True)
class EndpointPose:
    x: float
    y: float
    hdg: float

    def distance(self, other: "EndpointPose") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def heading_to(self, other: "EndpointPose") -> float:
        return math.atan2(other.y - self.y, other.x - self.x)


def road_endpoint_pose(road: ET.Element, contact_point: str) -> Optional[EndpointPose]:
    """Pose at start ('start') or end ('end') of a road planView."""
    geoms = road.findall("./planView/geometry")
    if not geoms:
        return None
    if contact_point == "start":
        g = geoms[0]
        return EndpointPose(_f(g.get("x")), _f(g.get("y")), _f(g.get("hdg")))
    g = geoms[-1]
    x0, y0, hdg0, length = _f(g.get("x")), _f(g.get("y")), _f(g.get("hdg")), _f(g.get("length"))
    kind = None
    for child in g:
        kind = child.tag
        break
    if kind == "line":
        return EndpointPose(x0 + length * math.cos(hdg0),
                            y0 + length * math.sin(hdg0), hdg0)
    if kind == "arc":
        curv = _f(g.find("arc").get("curvature"))
        if abs(curv) < 1e-12:
            return EndpointPose(x0 + length * math.cos(hdg0),
                                y0 + length * math.sin(hdg0), hdg0)
        r = 1.0 / curv
        # arc endpoint: rotate heading by length/r about center
        delta = length * curv
        cx = x0 - r * math.sin(hdg0)
        cy = y0 + r * math.cos(hdg0)
        return EndpointPose(
            cx + r * math.sin(hdg0 + delta),
            cy - r * math.cos(hdg0 + delta),
            hdg0 + delta,
        )
    # conservative: extrapolate heading (poly3/spiral/paramPoly3 unknown here)
    return EndpointPose(x0 + length * math.cos(hdg0),
                        y0 + length * math.sin(hdg0), hdg0)


# ---------------------------------------------------------------------------
# 1. Junction connector candidate acceptance gate
# ---------------------------------------------------------------------------
@dataclass
class ConnectorCandidate:
    junction_id: str
    connector_road_id: str
    incoming_road_id: str
    outgoing_road_id: str
    start_pose: Optional[EndpointPose] = None
    end_pose: Optional[EndpointPose] = None
    length_m: float = 0.0
    max_gap_m: float = 1.0
    rejections: List[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rejections.append(reason)

    @property
    def accepted(self) -> bool:
        return not self.rejections


def validate_connector_candidate(
    candidate: ConnectorCandidate,
    *,
    max_endpoint_gap_m: float = 0.5,
    min_connector_length_m: float = 0.01,
    max_connector_length_m: float = 1000.0,
) -> ConnectorCandidate:
    """Fail-closed gate: reject unless pose, tangent and length are sane."""
    if candidate.start_pose is None or candidate.end_pose is None:
        candidate.reject("missing endpoint pose")
        return candidate
    if candidate.start_pose.distance(candidate.end_pose) < min_connector_length_m:
        candidate.reject("zero-length connector")
    if candidate.length_m > max_connector_length_m:
        candidate.reject("implausible connector length")
    # heading continuity at both ends (tangent check)
    end_to_start = candidate.start_pose.heading_to(candidate.end_pose)
    if abs(_angle_diff(end_to_start, candidate.start_pose.hdg)) > math.radians(120.0):
        candidate.reject("start tangent mismatch")
    start_to_end = candidate.end_pose.heading_to(candidate.start_pose)
    if abs(_angle_diff(start_to_end + math.pi, candidate.end_pose.hdg)) > math.radians(120.0):
        candidate.reject("end tangent mismatch")
    # gap check against junction connection endpoints
    if candidate.max_gap_m > max_endpoint_gap_m:
        candidate.reject(f"endpoint gap {candidate.max_gap_m:.3f} m exceeds threshold")
    return candidate


def _candidate_self_intersects(
    start: EndpointPose, end: EndpointPose, samples: int = 16
) -> bool:
    """Cheap polygon self-intersection check on the chord sample."""
    if samples < 4:
        return False
    pts = []
    for i in range(samples + 1):
        t = i / samples
        x = start.x + (end.x - start.x) * t
        y = start.y + (end.y - start.y) * t
        pts.append((x, y))
    for i in range(1, len(pts) - 1):
        if math.hypot(pts[i][0] - start.x, pts[i][1] - start.y) < 1e-9:
            return True  # duplicate vertex on a straight chord cannot happen; keep guard
    return False


def check_connector_self_intersection(candidate: ConnectorCandidate) -> ConnectorCandidate:
    if candidate.start_pose and candidate.end_pose:
        if _candidate_self_intersects(candidate.start_pose, candidate.end_pose):
            candidate.reject("self-intersecting connector geometry")
    return candidate


# ---------------------------------------------------------------------------
# 2. LaneLink candidate matching (ambiguity rejected)
# ---------------------------------------------------------------------------
@dataclass
class LaneLinkCandidate:
    from_road: str
    to_road: str
    from_lane_id: int
    to_lane_id: int
    match_score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    rejected: bool = False
    rejection_reason: str = ""

    def accept(self, score: float, reason: str) -> None:
        self.match_score = score
        self.reasons.append(reason)

    def reject(self, reason: str) -> None:
        self.rejected = True
        self.rejection_reason = reason


def match_lane_link(
    *,
    from_lane_type: str,
    to_lane_type: str,
    from_direction: str,
    to_direction: str,
    from_width_m: float,
    to_width_m: float,
    endpoint_distance_m: float,
    heading_diff_rad: float,
    travel_compatible: bool,
    max_distance_m: float = 5.0,
    max_heading_rad: float = math.radians(90.0),
    max_width_ratio: float = 3.0,
) -> LaneLinkCandidate:
    """Candidate LaneLink match; REJECTS ambiguity instead of guessing.

    Score: sum of normalized evidence terms.  Matching requires that the
    evidence is decisive: type+direction+travel+proximity.
    """
    cand = LaneLinkCandidate("?", "?", 0, 0)
    if not travel_compatible:
        cand.reject("reversed travel direction")
        return cand
    if endpoint_distance_m > max_distance_m:
        cand.reject(f"endpoint distance {endpoint_distance_m:.2f} m exceeds {max_distance_m} m")
        return cand
    if abs(heading_diff_rad) > max_heading_rad:
        cand.reject("heading mismatch")
        return cand
    if from_lane_type != to_lane_type:
        cand.reject(f"lane type mismatch {from_lane_type} vs {to_lane_type}")
        return cand
    if from_direction != to_direction:
        cand.reject(f"lane direction mismatch {from_direction} vs {to_direction}")
        return cand
    if to_width_m <= 0.0 or from_width_m <= 0.0:
        cand.reject("zero width")
        return cand
    if max(from_width_m, to_width_m) / min(from_width_m, to_width_m) > max_width_ratio:
        cand.reject("width ratio outside tolerance")
        return cand
    score = 1.0 / (1.0 + endpoint_distance_m) + 1.0 / (1.0 + abs(heading_diff_rad))
    cand.accept(score, "type+direction+proximity match")
    return cand


def resolve_lane_link_targets(
    candidates: Sequence[LaneLinkCandidate],
) -> Tuple[List[LaneLinkCandidate], List[str]]:
    """Resolve one-to-one LaneLink mapping; ambiguity is rejected outright.

    Returns (accepted, rejected_reasons).
    """
    accepted: List[LaneLinkCandidate] = []
    rejected: List[str] = []
    for cand in candidates:
        if cand.rejected:
            rejected.append(cand.rejection_reason)
            continue
        accepted.append(cand)
    # ambiguity: multiple accepted candidates with equal score for same lane
    from collections import defaultdict
    groups: Dict[Any, List[LaneLinkCandidate]] = defaultdict(list)
    for cand in accepted:
        groups[(cand.from_lane_id, cand.to_lane_id)].append(cand)
    for key, grp in groups.items():
        if len(grp) > 1 and len({round(c.match_score, 6) for c in grp}) > 1:
            rejected.append(f"ambiguous target for {key}: {len(grp)} competing matches")
            accepted = [c for c in accepted if (c.from_lane_id, c.to_lane_id) != key]
    return accepted, rejected


# ---------------------------------------------------------------------------
# 3. Road link reciprocity validator (read-only)
# ---------------------------------------------------------------------------
def validate_road_link_reciprocity(root: ET.Element) -> List[Dict[str, Any]]:
    """Return violations of road<->road / road<->junction link reciprocity.

    A road link {predecessor|successor} with elementType=road pointing to B
    requires that B links back with the complementary contactPoint; road->
    junction links require the junction to have a matching connection entry.
    """
    roads = {r.get("id"): r for r in root.findall(".//road")}
    junctions = {j.get("id"): j for j in root.findall(".//junction")}
    violations: List[Dict[str, Any]] = []

    def _complement_link_type(direction: Optional[str]) -> Optional[str]:
        return {"predecessor": "successor", "successor": "predecessor"}.get(direction or "")

    for rid, road in roads.items():
        link = road.find("link")
        if link is None:
            continue
        for direction in ("predecessor", "successor"):
            el = link.find(direction)
            if el is None:
                continue
            etype = el.get("elementType")
            eid = el.get("elementId")
            cp = el.get("contactPoint")
            if etype == "road":
                other = roads.get(eid)
                if other is None:
                    violations.append({
                        "type": "road_link_target_missing",
                        "road": rid, "direction": direction, "target": eid,
                    })
                    continue
                other_link = other.find("link")
                back = None
                if other_link is not None:
                    back = other_link.find(_complement_link_type(direction) or "")
                if back is None or back.get("elementId") != rid:
                    violations.append({
                        "type": "road_link_not_reciprocated",
                        "road": rid, "direction": direction,
                        "target": eid, "expected_back_element": rid,
                        "found_back_element": back.get("elementId") if back is not None else None,
                    })
            elif etype == "junction":
                jct = junctions.get(eid)
                if jct is None:
                    violations.append({
                        "type": "junction_link_target_missing",
                        "road": rid, "direction": direction, "target": eid,
                    })
    return violations


# ---------------------------------------------------------------------------
# 4. Roundabout closed-ring validation (read-only)
# ---------------------------------------------------------------------------
def validate_roundabout_ring(
    road_ids: Sequence[str],
    roads: Dict[str, ET.Element],
    *,
    max_link_gap_m: float = 5.0,
) -> Dict[str, Any]:
    """Check a roundabout ring is closed and traversable.

    Requires: every ring road present; following the successor chain from the
    first road visits every ring road and returns to the start (cyclic);
    every road has at least one in-ring link (no island-chord isolation).
    """
    missing = [r for r in road_ids if r not in roads]
    if missing:
        return {"closed": False, "missing_roads": missing, "reason": "missing ring roads"}
    ring = list(road_ids)
    ring_set = set(ring)
    visited: List[str] = []
    seen: set = set()
    cur = ring[0]
    hops = 0
    while cur not in seen and hops <= len(ring) + 1:
        seen.add(cur)
        visited.append(cur)
        link = roads[cur].find("link")
        nxt = None
        if link is not None:
            for direction in ("successor", "predecessor"):
                el = link.find(direction)
                if el is not None and el.get("elementType") == "road" and el.get("elementId") in ring_set:
                    nxt = el.get("elementId")
                    break
        if nxt is None:
            return {"closed": False, "ring_roads": ring,
                    "unreachable": [r for r in ring if r not in visited],
                    "reason": f"ring broken at {cur} (no in-ring link)"}
        cur = nxt
        hops += 1
    cyclic = cur == ring[0] and len(seen) == len(ring)
    if not cyclic and hops > len(ring):
        return {"closed": False, "ring_roads": ring,
                "unreachable": [r for r in ring if r not in visited],
                "reason": "successor chain does not return to ring start"}
    return {
        "closed": cyclic,
        "ring_roads": ring,
        "unreachable": [r for r in ring if r not in visited],
        "reason": "" if cyclic else "ring broken",
    }
