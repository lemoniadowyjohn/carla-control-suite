#!/usr/bin/env python3
"""P0-B orphan connection repair (fail-closed, deterministic).

Finds fully-disconnected drivable roads (ORPHAN_FULLY_DISCONNECTED per
CLOSURE-18) and attempts to connect them to nearby junction-connected
roads when geometric proximity AND orientation support a connection.
Residuals that cannot be connected are reported (evidence) — never hidden
unless strict mode is enabled, in which case residuals raise.

Behaviour (L1/L2, reviewed):
- Endpoints are derived from planView; XODR hdg is already radians (never
  re-converted). Zero-curvature <arc> is treated as a straight line.
- Cross-side continuations (orphan-end <-> target-start or orphan-start
  <-> target-end) need near-EQUAL headings; same-side meetings
  (start<->start, end<->end) need near-OPPOSITE headings. Heights must
  match within tolerance. Duplicate/overlapping same-direction roads are
  therefore rejected.
- Reciprocal road->road links are written with ASAM contactPoint
  semantics (contactPoint names the contact on the LINKED element).
- A predecessor/successor slot that is already occupied is never
  overwritten; the pairing is refused and counted as a residual.
- <link> is inserted as the first child of <road> (XODR schema order).
- Targets are roads participating in at least one junction connection;
  the orphan itself must not be a junction member.

This module does NOT invent synthetic lane topology and does not route
links through junction internals; it only creates road-to-road links.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import math

from ultimate_pipeline.core.repair_diff import diff_log
from ultimate_pipeline.geometry.opendrive_geometry_kernel import (
    endpoint as _kernel_endpoint,
    pose_at_s as _kernel_pose_at_s,
)

Point = Tuple[float, float]


def _safe_float(x, default=0.0) -> float:
    try:
        return float(str(x).strip()) if x is not None else float(default)
    except (ValueError, TypeError):
        return float(default)


def _road_endpoints(road: ET.Element) -> List[Point]:
    """Return (start_x, start_y) and (end_x, end_y) from first/last geometry.

    L1 review fix (defect A): this used to hand-roll the end-point math
    (chord-projection along the END heading), which is only correct for a
    straight <line>; <arc> (nonzero curvature), <spiral>, <poly3> and
    <paramPoly3> all fell through to that same formula and were wrong (a
    paramPoly3 curving to (100, 16.67) was reported at (100, 0), a 16.7 m
    error). This now delegates to the canonical kernel
    (ultimate_pipeline.geometry.opendrive_geometry_kernel), which evaluates
    every ASAM OpenDRIVE primitive exactly.

    Returns [] if planView has no geometries, or if any primitive is
    unsupported/malformed (the kernel raises ValueError) -- callers must
    treat that as a residual ('unsupported_geometry'), never guess an
    endpoint.
    """
    geoms = sorted(
        list(road.findall("./planView/geometry")),
        key=lambda g: _safe_float(g.get("s"), 0.0),
    )
    if not geoms:
        return []
    try:
        start_pose = _kernel_pose_at_s(geoms[0], 0.0)
        end_pose = _kernel_endpoint(geoms[-1])
    except (ValueError, ZeroDivisionError):
        return []
    return [(start_pose.x, start_pose.y), (end_pose.x, end_pose.y)]


def _road_z(road: ET.Element, s: float = 0.0) -> float:
    """Approximate Z at given s position from elevationProfile."""
    elev = road.find("./elevationProfile")
    if elev is None:
        return 0.0
    best_z = 0.0
    for e in elev.findall("elevation"):
        if _safe_float(e.get("s"), 0.0) <= s:
            best_z = _safe_float(e.get("a"), 0.0) + _safe_float(e.get("b"), 0.0) * (s - _safe_float(e.get("s"), 0.0)) + \
                     _safe_float(e.get("c"), 0.0) * (s - _safe_float(e.get("s"), 0.0))**2 + \
                     _safe_float(e.get("d"), 0.0) * (s - _safe_float(e.get("s"), 0.0))**3
    return best_z


def _heading_at_end(road: ET.Element) -> float:
    """Return heading (radians) at road end via the canonical geometry
    kernel (see _road_endpoints for the defect this replaces).

    Returns 0.0 if planView has no geometries or the primitive is
    unsupported/malformed; callers that must distinguish "no heading" from
    "zero heading" check _road_endpoints(road) first (it returns [] in
    exactly those cases).
    """
    geoms = sorted(
        list(road.findall("./planView/geometry")),
        key=lambda g: _safe_float(g.get("s"), 0.0),
    )
    if not geoms:
        return 0.0
    try:
        return _kernel_endpoint(geoms[-1]).heading
    except (ValueError, ZeroDivisionError):
        return 0.0


def _heading_at_start(road: ET.Element) -> Optional[float]:
    """Return heading (radians) at road start via the canonical geometry
    kernel, or None if planView has no geometries or the primitive is
    unsupported/malformed.

    L1 review fix (defect A): the previous call sites read the first
    geometry's raw `hdg` attribute directly, which is only the true start
    heading for primitives with zero initial local heading (line, arc,
    spiral, paramPoly3 with bU/bV such that atan2(bV,bU)==0); for a <poly3>
    with nonzero `b`, the true start heading differs from `hdg` by
    atan2(b, 1). Delegating to the kernel's pose_at_s(geom, 0) is correct
    for every primitive.
    """
    geoms = sorted(
        list(road.findall("./planView/geometry")),
        key=lambda g: _safe_float(g.get("s"), 0.0),
    )
    if not geoms:
        return None
    try:
        return _kernel_pose_at_s(geoms[0], 0.0).heading
    except (ValueError, ZeroDivisionError):
        return None


def _link_slot_occupied(road: ET.Element, link_type: str) -> bool:
    """True if road already carries a predecessor/successor element of link_type.

    L1-L2 review fix: any existing element blocks the slot.  XODR allows at
    most one predecessor and one successor element per road link, so
    overwriting an existing one would silently destroy a real connection
    (observed as a destroyed junction link in review probe BLOCKER-2).
    """
    link = road.find("link")
    if link is None:
        return False
    return link.find(link_type) is not None


def _add_road_link(road: ET.Element, target_id: str, contact_point: str, link_type: str) -> None:
    """Add predecessor or successor link to road with contactPoint.

    L1-L2 review fix: the caller must guarantee the slot is free
    (_link_slot_occupied == False); this function creates NEW elements only.
    """
    link = road.find("link")
    if link is None:
        # L1-L2 review fix: XODR schema order -> <link> must precede
        # <planView>; append-at-end produced planView, lanes, link (invalid
        # sequence).  Insert as the first child of <road>.
        link = ET.Element("link")
        road.insert(0, link)
    elem = ET.SubElement(link, link_type)
    elem.set("elementType", "road")
    elem.set("elementId", target_id)
    elem.set("contactPoint", contact_point)


def _build_source_authority_pairs(
    osm_ways: Optional[Sequence[Mapping[str, Any]]],
    associations: Optional[Mapping[str, Mapping[str, Any]]],
    *,
    vehicle_class: str = "motor_vehicle",
) -> Tuple[Set[Tuple[str, str]], Dict[str, Any]]:
    """Road-id pairs whose connection is **proven by the OSM source**.

    A pair ``(orphan_road_id, target_road_id)`` is proven only when the two
    roads correspond to OSM ways that share an OSM node and that node is
    traversable for the vehicle class.  Geometry is not consulted here at
    all -- geometry may only veto a proven pair later, never create one.
    """
    info: Dict[str, Any] = {
        "enabled": bool(osm_ways) and bool(associations),
        "proven_pair_count": 0,
        "reason": "",
    }
    if not osm_ways or not associations:
        info["reason"] = "osm_source_unavailable"
        return set(), info

    from ultimate_pipeline.quality.osm_road_link_topology import (
        build_osm_source_adjacency,
    )

    adjacency = build_osm_source_adjacency(osm_ways, vehicle_class=vehicle_class)

    road_by_way: Dict[str, str] = {}
    for road_id, association in associations.items():
        if not isinstance(association, Mapping):
            continue
        way_id = str(association.get("osm_way_id", "")).strip()
        if way_id:
            road_by_way.setdefault(way_id, str(road_id))

    proven: Set[Tuple[str, str]] = set()
    for way_id, road_id in road_by_way.items():
        for key, neighbours in adjacency["adjacent_by_way_node"].items():
            if not key.startswith(f"{way_id}@"):
                continue
            for neighbour in neighbours:
                neighbour_road = road_by_way.get(str(neighbour))
                if not neighbour_road or neighbour_road == road_id:
                    continue
                proven.add((road_id, neighbour_road))
                proven.add((neighbour_road, road_id))

    info["proven_pair_count"] = len(proven)
    info["reason"] = "source_proven"
    return proven, info


def repair_orphan_roads(
    root: ET.Element,
    max_snap_m: float = 5.0,
    max_heading_diff_deg: float = 30.0,
    max_height_diff_m: float = 1.0,
    strict: bool = False,
    osm_ways: Optional[Sequence[Mapping[str, Any]]] = None,
    associations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    vehicle_class: str = "motor_vehicle",
    require_source_authority: bool = True,
) -> Dict[str, Any]:
    """P0-B source-stage repair: connect orphan roads within max_snap_m.

    L1/L2: fail-closed, reciprocal links, contactPoint, junction avoidance.

    V103-O3 (registry **T03**): a repair is only performed when the OSM
    source **proves** the connection.  Geometric proximity, heading and Z
    are *necessary filters applied after* the source proof -- they can veto
    a proven candidate, they can never create one.  Without OSM source
    evidence the orphan stays unconnected and the residual reason says so.

    ``require_source_authority=False`` restores the pre-V103 geometry-only
    behaviour for callers that explicitly opt out (the source-stage caller
    in ``stage_03_topology_repair.py`` does not opt out).
    """
    proven_pairs, source_info = _build_source_authority_pairs(
        osm_ways, associations, vehicle_class=vehicle_class
    )
    if require_source_authority and not source_info["enabled"]:
        source_info["reason"] = "osm_source_unavailable"

    road_ids: Dict[str, ET.Element] = {
        str(r.get("id")).strip(): r
        for r in root.findall("road")
        if r.get("id")
    }
    junction_ids: Set[str] = {
        str(j.get("id")).strip()
        for j in root.findall("junction")
        if j.get("id")
    }
    # Build junction connection membership (both incomingRoad and
    # connectingRoad ids -- a road that is a MEMBER of a junction, in
    # either role, must not itself be treated as a repairable orphan).
    junction_roads: Set[str] = set()
    for junc in root.findall("junction"):
        for conn in junc.findall("connection"):
            inc = str(conn.get("incomingRoad") or "").strip()
            con = str(conn.get("connectingRoad") or "").strip()
            if inc:
                junction_roads.add(inc)
            if con:
                junction_roads.add(con)

    # Identify orphans: driving lanes present but no link at all, not in junction
    orphan_ids: List[str] = []
    for rid, road in road_ids.items():
        if rid not in junction_roads:
            links = road.find("link")
            pred = links.find("predecessor") if links is not None else None
            succ = links.find("successor") if links is not None else None
            has_link = (pred is not None) or (succ is not None)
            driving_lanes = 0
            lanes_elem = road.find("lanes")
            if lanes_elem is not None:
                for sec in lanes_elem.findall("laneSection"):
                    for side in ("left", "right"):
                        side_el = sec.find(side)
                        if side_el is None:
                            continue
                        for lane in side_el.findall("lane"):
                            if (str(lane.get("type") or "driving").lower() == "driving"):
                                driving_lanes += 1
            if not has_link and driving_lanes > 0:
                orphan_ids.append(rid)

    # Repair: for each orphan, try geometric snap to nearest connected road
    repaired = 0
    residuals = 0
    errors = []
    residual_reasons: Dict[str, int] = {}
    source_refused = 0

    def _bump_reason(reason: str) -> None:
        residual_reasons[reason] = residual_reasons.get(reason, 0) + 1

    # Connected roads = in junction_roads (have at least one junction connection)
    # Exclude roads already in junction to avoid linking to junction internals
    connected_roads: List[str] = [
        rid for rid in road_ids if rid not in orphan_ids and rid in junction_roads
    ]
    # Also exclude target roads that already have a link at the matching endpoint
    # (they're already connected to a junction at that end)

    for rid in orphan_ids:
        orphan_road = road_ids.get(rid)
        if orphan_road is None:
            continue
        orphan_ends = _road_endpoints(orphan_road)
        if len(orphan_ends) < 2:
            residuals += 1
            _bump_reason("unsupported_geometry")
            continue

        orphan_hdg_start = _heading_at_start(orphan_road) or 0.0
        orphan_hdg_end = _heading_at_end(orphan_road)
        orphan_z_start = _road_z(orphan_road, 0.0)
        orphan_z_end = _road_z(orphan_road, _safe_float(
            orphan_road.find("./planView/geometry[last()]").get("length") if orphan_road.find("./planView/geometry[last()]") is not None else 0.0, 0.0))

        best_target = None
        best_dist_sq = max_snap_m**2
        best_target_idx = None
        best_orphan_idx = None
        best_target_is_start = True
        # L1 review fix (defect B): track whether a geometrically-close
        # candidate was rejected ONLY because it is a junction-internal
        # connector road, so the residual reason is accurate.
        target_is_junction_internal_hit = False
        # Per-orphan flag: did the OSM source refuse a geometric candidate?
        orphan_source_refused = False

        # Try nearest connected road endpoint
        for target_rid in connected_roads:
            target_road = road_ids.get(target_rid)
            if target_road is None:
                continue
            target_ends = _road_endpoints(target_road)
            if len(target_ends) < 2:
                continue

            target_hdg_start = _heading_at_start(target_road) or 0.0
            target_hdg_end = _heading_at_end(target_road)
            target_z_start = _road_z(target_road, 0.0)
            target_z_end = _road_z(target_road, _safe_float(
                target_road.find("./planView/geometry[last()]").get("length") if target_road.find("./planView/geometry[last()]") is not None else 0.0, 0.0))

            for target_idx, tp in enumerate(target_ends):
                target_hdg = target_hdg_start if target_idx == 0 else target_hdg_end
                target_z = target_z_start if target_idx == 0 else target_z_end
                target_is_start = (target_idx == 0)

                for orphan_idx, op in enumerate(orphan_ends):
                    orphan_hdg = orphan_hdg_start if orphan_idx == 0 else orphan_hdg_end
                    orphan_z = orphan_z_start if orphan_idx == 0 else orphan_z_end
                    orphan_is_start = (orphan_idx == 0)

                    dx = op[0] - tp[0]
                    dy = op[1] - tp[1]
                    d_sq = dx * dx + dy * dy
                    if d_sq >= best_dist_sq:
                        continue

                    # L1 review fix (defect B): candidate targets come from
                    # junction_roads, which contains BOTH incomingRoad ids
                    # (ordinary external roads, junction=="-1") AND
                    # connectingRoad ids (junction-internal connector
                    # roads, junction==<junction id>). Only the former may
                    # be a repair target -- linking an orphan straight to a
                    # connector bypasses the junction and is topologically
                    # wrong (reviewer-reproduced: an orphan near a
                    # connector's far end was silently linked to it).
                    if str(target_road.get("junction", "-1") or "-1").strip() != "-1":
                        target_is_junction_internal_hit = True
                        continue

                    # L1: heading difference check, direction-aware.
                    # Cross-side continuation (orphan-end <-> target-start or
                    # orphan-start <-> target-end): headings must be near equal.
                    # Same-side meeting (start <-> start or end <-> end):
                    # roads meet head-to-head/tail-to-tail, so headings must be
                    # near OPPOSITE.  The previous single rule accepted two
                    # overlapping same-direction roads as valid neighbours.
                    same_side = (orphan_idx == 0) == (target_idx == 0)
                    hdg_diff = abs((orphan_hdg - target_hdg + math.pi) % (2 * math.pi) - math.pi)
                    if same_side:
                        opposite_gap = abs(math.pi - hdg_diff)
                        if math.degrees(opposite_gap) > max_heading_diff_deg:
                            continue
                    else:
                        if math.degrees(hdg_diff) > max_heading_diff_deg:
                            continue

                    # L1: height difference check
                    if abs(orphan_z - target_z) > max_height_diff_m:
                        continue

                    # L1-L2 review fix: occupancy is a slot-level test.  XODR
                    # permits one predecessor and one successor per road link,
                    # so refuse any pairing that would need to overwrite an
                    # existing element instead of mutating it silently.
                    orphan_link_type_needed = "predecessor" if orphan_idx == 0 else "successor"
                    target_link_type_needed = "predecessor" if target_idx == 0 else "successor"
                    if _link_slot_occupied(orphan_road, orphan_link_type_needed):
                        continue
                    if _link_slot_occupied(target_road, target_link_type_needed):
                        continue

                    # V103-O3 (registry T03): the OSM source must PROVE this
                    # connection.  Geometric proximity + heading + Z are
                    # necessary filters applied *after* the proof; they can
                    # only veto a candidate, never create one.
                    if require_source_authority:
                        if (rid, target_rid) not in proven_pairs:
                            source_refused += 1
                            orphan_source_refused = True
                            continue

                    # All checks passed
                    best_dist_sq = d_sq
                    best_target = target_rid
                    best_target_idx = target_idx
                    best_orphan_idx = orphan_idx
                    best_target_is_start = target_is_start

        if best_target:
            target_road = road_ids[best_target]

            # L1/L2: Determine link type based on orphan endpoint
            # If orphan end matched target start -> orphan successor to target, target predecessor from orphan
            # If orphan end matched target end -> orphan predecessor to target, target successor from orphan
            # If orphan start matched target start -> orphan predecessor from target, target predecessor from orphan
            # If orphan start matched target end -> orphan successor to target, target successor from orphan

            orphan_is_start = (best_orphan_idx == 0)
            target_is_start = best_target_is_start

            if orphan_is_start and target_is_start:
                # orphan start to target start (head-to-head):
                # orphan predecessor -> linked target touched at its start;
                # target predecessor -> linked orphan touched at its start.
                orphan_link_type = "predecessor"
                target_link_type = "predecessor"
                orphan_contact = "start"
                target_contact = "start"
            elif orphan_is_start and not target_is_start:
                # orphan start to target end (chain head-to-tail):
                # L1-L2 review fix: contactPoint names the contact point on the
                # LINKED element (ASAM OpenDRIVE 10.3).  Orphan predecessor
                # points at the target and touches it at target's END; target
                # successor points at the orphan and touches it at orphan's
                # START.  The previous values were inverted.
                orphan_link_type = "predecessor"
                target_link_type = "successor"
                orphan_contact = "end"
                target_contact = "start"
            elif not orphan_is_start and target_is_start:
                # orphan end to target start (chain tail-to-head):
                # L1-L2 review fix: orphan successor touches the target at its
                # START; target predecessor touches the orphan at its END.
                # The previous values were inverted.
                orphan_link_type = "successor"
                target_link_type = "predecessor"
                orphan_contact = "start"
                target_contact = "end"
            else:  # not orphan_is_start and not target_is_start
                # orphan end to target end (tail-to-tail):
                # orphan successor -> linked target touched at its end;
                # target successor -> linked orphan touched at its end.
                orphan_link_type = "successor"
                target_link_type = "successor"
                orphan_contact = "end"
                target_contact = "end"

            # Re-check occupancy right before mutation in case an earlier loop
            # iteration consumed one of the slots after selection.
            if _link_slot_occupied(orphan_road, orphan_link_type) or \
                    _link_slot_occupied(target_road, target_link_type):
                residuals += 1
                _bump_reason("slot_occupied_at_commit")
                continue

            # L2: Add reciprocal links with contactPoint
            _add_road_link(orphan_road, best_target, orphan_contact, orphan_link_type)
            _add_road_link(target_road, rid, target_contact, target_link_type)

            repaired += 1
        else:
            # No nearby connection possible within threshold
            residuals += 1
            if orphan_source_refused:
                # The geometry found a candidate but the OSM source did not
                # prove the connection (registry T03).  Report the source
                # refusal, not a geometric miss.
                _bump_reason("no_source_proof")
            elif target_is_junction_internal_hit:
                _bump_reason("target_is_junction_internal")
            else:
                _bump_reason("no_target_within_threshold")

    if strict and residuals > 0:
        # L1-L2 review fix: strict means ZERO residual orphans, regardless of
        # how many were repaired; the old `repaired == 0` condition reported
        # success with orphans still unconnected.
        raise RuntimeError(
            f"P0-B orphan repair: {residuals} residual unconnected orphans, "
            f"repaired={repaired}, "
            f"max_snap_m={max_snap_m}, max_heading_diff_deg={max_heading_diff_deg}, "
            f"max_height_diff_m={max_height_diff_m}"
        )

    return {
        "ok": repaired > 0 or len(orphan_ids) == 0,
        "repair_type": "P0-B_orphan_road_connection_repair",
        "orphan_roads_found": len(orphan_ids),
        "repaired_connections": repaired,
        "residual_unconnected": residuals,
        # V103-O3 (registry T03): a repair is only performed with positive
        # OSM graph evidence.  Geometry alone is never sufficient.
        "source_authority": {
            "required": bool(require_source_authority),
            "enabled": source_info["enabled"],
            "reason": source_info["reason"],
            "proven_pair_count": source_info["proven_pair_count"],
            "geometry_only_candidates_refused": source_refused,
        },
        "residual_reasons": residual_reasons,
        "threshold_m": max_snap_m,
        "max_heading_diff_deg": max_heading_diff_deg,
        "max_height_diff_m": max_height_diff_m,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# V103-O3: OSM-source reconciliation (registry T03 / R15 / OSM-04)
# ---------------------------------------------------------------------------

ORPHAN_STATUS_REPAIRED = "REPAIRED"
ORPHAN_STATUS_UNRESOLVED = "UNRESOLVED"
ORPHAN_STATUS_SKIPPED = "SKIPPED"

#: Maximum planar distance (m) between the two roads' closest geometry
#: points for a source-proven candidate to survive the *geometric* filter.
DEFAULT_MAX_GAP_M = 25.0

#: Maximum absolute Z difference (m) at the closest points.
DEFAULT_MAX_DZ_M = 2.0


def find_orphan_roads(root: ET.Element) -> List[str]:
    """XODR road ids that are completely isolated from the link graph.

    An orphan is a road that declares **no** ``predecessor`` and **no**
    ``successor`` element at all -- it cannot be reached from anywhere.

    A road that links to a junction is *not* an orphan: the junction (or the
    connector roads registered in it) provides the connection.
    """
    orphans: List[str] = []
    for road in root.findall("./road"):
        road_id = str(road.get("id", "")).strip()
        if not road_id:
            continue
        has_any_link = False
        for role in ("predecessor", "successor"):
            links = road.find("link")
            if links is not None and links.find(role) is not None:
                has_any_link = True
                break
        if not has_any_link:
            orphans.append(road_id)
    return sorted(orphans)


def find_unreachable_roads(root: ET.Element) -> List[str]:
    """Roads that declare links but are registered nowhere reachable.

    This is the stricter notion behind the registry's "orphan *drivable*
    roads": a road is drivable (it has lane geometry and link elements) but
    it cannot be reached, because every link it declares points at a
    junction that never lists it in a ``<connection>``.
    """
    registered: Set[str] = set()
    for junction in root.findall("./junction"):
        for connection in junction.findall("./connection"):
            for attribute in ("incomingRoad", "connectingRoad", "road"):
                value = connection.get(attribute)
                if value:
                    registered.add(str(value))

    # V104 review 4551845539: a road linked DIRECTLY to another road is
    # reachable through that link even when it appears in no junction
    # connection.  Compute reachability transitively from the junction
    # roots over road-to-road links, so a reciprocal chain leading to a
    # registered junction road is not reported as unreachable.
    road_links: Dict[str, Set[str]] = {}
    for road in root.findall("./road"):
        road_id = str(road.get("id", "")).strip()
        if not road_id:
            continue
        targets: Set[str] = set()
        links = road.find("link")
        if links is not None:
            for role in ("predecessor", "successor"):
                element = links.find(role)
                if element is None:
                    continue
                if (element.get("elementType") or "").strip().lower() == "road":
                    target = str(element.get("elementId") or "").strip()
                    if target:
                        targets.add(target)
        road_links[road_id] = targets

    reachable: Set[str] = set(registered)
    changed = True
    while changed:
        changed = False
        for road_id, targets in road_links.items():
            if road_id in reachable:
                continue
            if targets & reachable:
                reachable.add(road_id)
                changed = True

    unreachable: List[str] = []
    for road in root.findall("./road"):
        road_id = str(road.get("id", "")).strip()
        if not road_id or road_id in reachable:
            continue
        links = road.find("link")
        has_link = links is not None and (
            links.find("predecessor") is not None or links.find("successor") is not None
        )
        if not has_link:
            # Fully isolated: already reported as an orphan.
            continue
        unreachable.append(road_id)
    return sorted(unreachable)


def _reconcile_road_points(
    road: Optional[ET.Element],
) -> List[Tuple[float, float, float]]:
    """``(x, y, z)`` samples of one XODR road."""
    points: List[Tuple[float, float, float]] = []
    if road is None:
        return points
    elevation = road.find("./elevationProfile/elevation")
    z = 0.0
    if elevation is not None:
        try:
            z = float(elevation.get("a", "0"))
        except (TypeError, ValueError):
            z = 0.0
    for geometry in road.findall("./planView/geometry"):
        try:
            x = float(geometry.get("x", "0"))
            y = float(geometry.get("y", "0"))
        except (TypeError, ValueError):
            continue
        points.append((x, y, z))
        # V104 review 4551845553: a geometry primitive's ORIGIN is not the
        # whole road.  Two roads that touch end-to-end were sampled only at
        # their origins, so the measured gap was the full road length
        # instead of zero.  Include the primitive's endpoint.
        try:
            length = float(geometry.get("length", "0"))
            heading = float(geometry.get("hdg", "0"))
        except (TypeError, ValueError):
            length = 0.0
            heading = 0.0
        if length > 0.0:
            import math as _math

            points.append(
                (
                    x + length * _math.cos(heading),
                    y + length * _math.sin(heading),
                    z,
                )
            )
    return points


def _closest_gap(
    points_a: Sequence[Tuple[float, float, float]],
    points_b: Sequence[Tuple[float, float, float]],
) -> Tuple[float, float]:
    """Smallest planar distance and the Z difference at that pair."""
    best = (float("inf"), 0.0)
    for ax, ay, az in points_a:
        for bx, by, bz in points_b:
            gap = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            if gap < best[0]:
                best = (gap, abs(az - bz))
    return best


def reconcile_orphan_roads(
    root: ET.Element,
    *,
    osm_ways: Sequence[Mapping[str, Any]],
    associations: Mapping[str, Mapping[str, Any]],
    vehicle_class: str = "motor_vehicle",
    max_gap_m: float = DEFAULT_MAX_GAP_M,
    max_dz_m: float = DEFAULT_MAX_DZ_M,
) -> List[Dict[str, Any]]:
    """Reconcile every orphan road against the OSM source.

    A candidate is ``REPAIRED`` only when the OSM source proves exactly one
    continuation **and** the geometric filters do not veto it.  Anything the
    source cannot decide stays ``UNRESOLVED`` -- it is never repaired on a
    guess.
    """
    from ultimate_pipeline.quality.osm_road_link_topology import (
        build_osm_source_adjacency,
    )

    ways = list(osm_ways)
    adjacency = build_osm_source_adjacency(ways, vehicle_class=vehicle_class)

    node_refs_by_way: Dict[str, List[str]] = {}
    for way in ways:
        way_id = str(way.get("id", ""))
        refs = [str(r) for r in way.get("node_refs", ()) if r]
        if way_id and refs:
            node_refs_by_way[way_id] = refs

    road_by_way: Dict[str, str] = {}
    for road_id, association in sorted(associations.items()):
        if not isinstance(association, Mapping):
            continue
        way_id = str(association.get("osm_way_id", "")).strip()
        if way_id:
            road_by_way.setdefault(way_id, str(road_id))

    roads_by_id = {
        str(road.get("id", "")).strip(): road
        for road in root.findall("./road")
        if road.get("id")
    }

    results: List[Dict[str, Any]] = []
    for orphan_id in find_orphan_roads(root):
        association = associations.get(orphan_id)
        if not isinstance(association, Mapping):
            results.append(
                {
                    "xodr_road_id": orphan_id,
                    "status": ORPHAN_STATUS_UNRESOLVED,
                    "reason": "no_source_correspondence",
                    "source_way_id": "",
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": "",
                }
            )
            continue

        source_way_id = str(association.get("osm_way_id", ""))
        if not source_way_id:
            results.append(
                {
                    "xodr_road_id": orphan_id,
                    "status": ORPHAN_STATUS_UNRESOLVED,
                    "reason": "no_source_way",
                    "source_way_id": "",
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": "",
                }
            )
            continue

        proven: List[Tuple[str, str]] = []
        for node_id in node_refs_by_way.get(source_way_id, []):
            key = f"{source_way_id}@{node_id}"
            for neighbour in adjacency["adjacent_by_way_node"].get(key, ()):
                proven.append((node_id, str(neighbour)))

        if not proven:
            results.append(
                {
                    "xodr_road_id": orphan_id,
                    "status": ORPHAN_STATUS_UNRESOLVED,
                    "reason": "no_shared_osm_node",
                    "source_way_id": source_way_id,
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": "",
                }
            )
            continue

        orphan_points = _reconcile_road_points(roads_by_id.get(orphan_id))

        viable: List[Tuple[str, str, str, float, float]] = []
        for node_id, neighbour_way_id in proven:
            neighbour_road_id = road_by_way.get(neighbour_way_id)
            if not neighbour_road_id or neighbour_road_id == orphan_id:
                continue
            neighbour_points = _reconcile_road_points(
                roads_by_id.get(neighbour_road_id)
            )
            if not orphan_points or not neighbour_points:
                continue
            gap, dz = _closest_gap(orphan_points, neighbour_points)
            # Geometric filters are NECESSARY conditions applied AFTER the
            # source proof; they can only veto.
            if gap > max_gap_m or dz > max_dz_m:
                continue
            viable.append((node_id, neighbour_way_id, neighbour_road_id, gap, dz))

        if not viable:
            results.append(
                {
                    "xodr_road_id": orphan_id,
                    "status": ORPHAN_STATUS_UNRESOLVED,
                    "reason": "source_proof_rejected_by_geometry",
                    "source_way_id": source_way_id,
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": "",
                }
            )
            continue

        if len(viable) > 1:
            results.append(
                {
                    "xodr_road_id": orphan_id,
                    "status": ORPHAN_STATUS_UNRESOLVED,
                    "reason": "ambiguous_multiple_source_proven_continuations",
                    "source_way_id": source_way_id,
                    "neighbour_way_id": "",
                    "shared_node_id": "",
                    "neighbour_xodr_road_id": "",
                    "gap_m": "",
                    "dz_m": "",
                    "evidence": "candidate_count=%d" % len(viable),
                }
            )
            continue

        node_id, neighbour_way_id, neighbour_road_id, gap, dz = viable[0]
        results.append(
            {
                "xodr_road_id": orphan_id,
                "status": ORPHAN_STATUS_REPAIRED,
                "reason": "shared_osm_node_proven",
                "source_way_id": source_way_id,
                "neighbour_way_id": neighbour_way_id,
                "shared_node_id": node_id,
                "neighbour_xodr_road_id": neighbour_road_id,
                "gap_m": "%.3f" % gap,
                "dz_m": "%.3f" % dz,
                "evidence": "vehicle_class=%s;source_proof=shared_osm_node"
                % vehicle_class,
            }
        )
    return results


def write_orphan_reconciliation_csv(
    path: str,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    """Write the ``ORPHAN_ROAD_SOURCE_RECONCILIATION.csv`` deliverable."""
    import csv
    import os as _os

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "xodr_road_id",
        "status",
        "reason",
        "source_way_id",
        "neighbour_way_id",
        "shared_node_id",
        "neighbour_xodr_road_id",
        "gap_m",
        "dz_m",
        "evidence",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return str(target)
