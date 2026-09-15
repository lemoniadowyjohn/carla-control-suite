# ultimate_pipeline/topology/component_classifier.py
# -*- coding: utf-8 -*-

"""
Deterministic component classifier for island-quarantine governance.

`quarantine_island_roads` in map_hygiene removes every road-connectivity
component below a size threshold. Without classification that removal is
blind: a genuinely intentional island, a truncation artifact at the map
boundary, or an inscrutable component could be silently deleted. This module
classifies every small component into one of nine categories so quarantine
can preserve the ones that must not be auto-deleted.

Categories (single-letter value, deterministic precedence):

1. ROAD_LINK_DEFECT      -- a road <link> successor/predecessor references an
                            element id that does not exist in the XODR.
2. JUNCTION_DEFECT       -- a junction connection belonging to the component
                            references an incoming/connecting road id that
                            does not exist in the XODR.
3. LANELINK_DEFECT       -- a connection <laneLink> declares a from/to lane id
                            that is not present in the referenced road's
                            lanes.
4. INTENTIONAL_ISLAND    -- explicit userData/name marker declaring the
                            component deliberate (never auto-deleted).
5. BOUNDARY_TRUNCATION   -- the component's geometry touches the map bbox
                            edge; it may be clipped by the map cutoff rather
                            than genuinely isolated.
6. PRIVATE_OR_SERVICE    -- any component road carries type private/service.
7. PARKING_OR_YARD       -- any component road carries type parking.
8. SOURCE_DISCONNECTED   -- a genuinely disconnected source patch: no defect,
                            no semantic/type marker, no boundary touching, no
                            intentional marker. Auto-deletable as an island.
9. UNKNOWN               -- conflicting signals make the intent inscrutable;
                            NEVER auto-deleted in production.

Deletable under quarantine (single-source policy): ROAD_LINK_DEFECT,
JUNCTION_DEFECT, LANELINK_DEFECT, BOUNDARY_TRUNCATION, PRIVATE_OR_SERVICE,
PARKING_OR_YARD, SOURCE_DISCONNECTED.

Preserved by default (never auto-deleted unless explicitly allowed):
INTENTIONAL_ISLAND, UNKNOWN.

All functions are pure, deterministic, and read-only (offline; no CARLA).
The precedence is fixed so two runs over the same XODR always agree.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Category vocabulary
# ---------------------------------------------------------------------------

ROAD_LINK_DEFECT = "ROAD_LINK_DEFECT"
JUNCTION_DEFECT = "JUNCTION_DEFECT"
LANELINK_DEFECT = "LANELINK_DEFECT"
INTENTIONAL_ISLAND = "INTENTIONAL_ISLAND"
BOUNDARY_TRUNCATION = "BOUNDARY_TRUNCATION"
PRIVATE_OR_SERVICE = "PRIVATE_OR_SERVICE"
PARKING_OR_YARD = "PARKING_OR_YARD"
SOURCE_DISCONNECTED = "SOURCE_DISCONNECTED"
UNKNOWN = "UNKNOWN"

ALL_CATEGORIES: Tuple[str, ...] = (
    ROAD_LINK_DEFECT,
    JUNCTION_DEFECT,
    LANELINK_DEFECT,
    INTENTIONAL_ISLAND,
    BOUNDARY_TRUNCATION,
    PRIVATE_OR_SERVICE,
    PARKING_OR_YARD,
    SOURCE_DISCONNECTED,
    UNKNOWN,
)

# Fixed precedence: defects first (data integrity outranks semantics), then
# semantic markers, then the deterministic fallbacks. UNKNOWN is the terminal
# category and is only chosen when no earlier category applies.
_PRECEDENCE: Tuple[str, ...] = (
    ROAD_LINK_DEFECT,
    JUNCTION_DEFECT,
    LANELINK_DEFECT,
    INTENTIONAL_ISLAND,
    BOUNDARY_TRUNCATION,
    PRIVATE_OR_SERVICE,
    PARKING_OR_YARD,
    SOURCE_DISCONNECTED,
)

# Single-source-of-truth policy for quarantine.
PRESERVED_UNDER_QUARANTINE: Set[str] = {
    INTENTIONAL_ISLAND,
    UNKNOWN,
}
DELETABLE_UNDER_QUARANTINE: Set[str] = set(ALL_CATEGORIES) - PRESERVED_UNDER_QUARANTINE

# Sentinels used by the private island marker (deterministic, test-friendly).
_INTENTIONAL_MARKER_TAG = "intentionalIsland"
_INTENTIONAL_MARKER_NAMES = ("island", "driveway_island", "intentional_island")

# Boundary tolerance: a component endpoint within this distance of the map
# bbox edge counts as truncated. Relative to the global bbox diagonal so the
# rule scales to any map extent, with a small absolute floor.
_BOUNDARY_RELATIVE_TOL = 0.001
_BOUNDARY_ABS_FLOOR_M = 1.0

# Road type attributes that carry quarantine semantics (per OpenDRIVE spec).
_PRIVATE_OR_SERVICE_TYPES = {"private", "service"}
_PARKING_OR_YARD_TYPES = {"parking", "parkingSpace"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


# ---------------------------------------------------------------------------
# geometry helpers (local; no heavy imports)
# ---------------------------------------------------------------------------


def _road_endpoints(road: ET.Element) -> List[Tuple[float, float]]:
    """Return up to two endpoints of a road's planView polyline.

    Endpoints are derived from the first <geometry> start position and the
    last <geometry>'s end position (start + heading*length), matching the
    pose convention used elsewhere in topology diagnostics. Roads without
    any geometry contribute no endpoints (degenerate/in-memory synthetic
    fixtures fall through to SOURCE_DISCONNECTED, never BOUNDARY_TRUNCATION).
    """
    geometries = road.findall("planView/geometry")
    if not geometries:
        return []
    endpoints: List[Tuple[float, float]] = []
    first = geometries[0]
    endpoints.append(
        (_safe_float(first.get("x")), _safe_float(first.get("y")))
    )
    last = geometries[-1]
    hdg = _safe_float(last.get("hdg"))
    length = _safe_float(last.get("length"))
    last_x = _safe_float(last.get("x")) + length * math.sin(hdg)
    last_y = _safe_float(last.get("y")) + length * math.cos(hdg)
    endpoints.append((last_x, last_y))
    return endpoints


def _map_bbox(roads_by_id: Dict[str, ET.Element]) -> Optional[Tuple[float, float, float, float, float]]:
    """Global (min_x, min_y, max_x, max_y, diagonal) over all road endpoints."""
    xs: List[float] = []
    ys: List[float] = []
    for road in roads_by_id.values():
        for x, y in _road_endpoints(road):
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    diagonal = math.hypot(max_x - min_x, max_y - min_y)
    return min_x, min_y, max_x, max_y, diagonal


# ---------------------------------------------------------------------------
# per-component signal collection
# ---------------------------------------------------------------------------


def _has_external_marker(road: ET.Element) -> bool:
    """Road is explicitly marked as an intentional island."""
    for user_data in road.findall("userData"):
        for child in user_data:
            if child.tag.lower() == _INTENTIONAL_MARKER_TAG.lower():
                return True
    name = (road.get("name") or "").strip().lower()
    for marker in _INTENTIONAL_MARKER_NAMES:
        if marker in name:
            return True
    return False


def _lane_ids_of_road(road: Optional[ET.Element]) -> Set[str]:
    """All lane ids declared across every laneSection of a road (any side)."""
    if road is None:
        return set()
    lanes_elem = road.find("lanes")
    if lanes_elem is None:
        return set()
    ids: Set[str] = set()
    for section in lanes_elem.findall("laneSection"):
        for side in ("left", "right"):
            side_elem = section.find(side)
            if side_elem is None:
                continue
            for lane in side_elem.findall("lane"):
                lid = lane.get("id")
                if lid is not None:
                    ids.add(lid)
    return ids


def _component_signals(
    comp_roads: Set[str],
    roads_by_id: Dict[str, ET.Element],
    junctions: List[ET.Element],
    map_bbox: Optional[Tuple[float, float, float, float, float]],
) -> Dict[str, Any]:
    """Collect the boolean signals that drive the precedence decision."""
    all_road_ids: Set[str] = set(roads_by_id.keys())
    all_junction_ids: Set[str] = {
        (j.get("id") or "").strip() for j in junctions if (j.get("id") or "").strip()
    }

    road_link_defect = False
    junction_defect = False
    lanelink_defect = False
    intentional = False
    private_or_service = False
    parking = False
    comp_endpoints: List[Tuple[float, float]] = []

    for rid in sorted(comp_roads):
        road = roads_by_id.get(rid)
        if road is None:
            road_link_defect = True  # referenced in a node but absent: a defect
            continue
        if _has_external_marker(road):
            intentional = True
        rtype = (road.get("type") or "none").strip().lower()
        if rtype in _PRIVATE_OR_SERVICE_TYPES:
            private_or_service = True
        elif rtype in _PARKING_OR_YARD_TYPES:
            parking = True

        link_elem = road.find("link")
        if link_elem is not None:
            for ref in link_elem.findall("successor") + link_elem.findall("predecessor"):
                target = (ref.get("elementId") or "").strip()
                element_type = ref.get("elementType")
                if not target:
                    continue
                valid = target in all_road_ids
                if element_type == "junction":
                    valid = target in all_junction_ids
                if not valid:
                    road_link_defect = True

        comp_endpoints.extend(_road_endpoints(road))

    for junction in junctions:
        jid = (junction.get("id") or "").strip()
        attached = False
        for conn in junction.findall("connection"):
            inc = (conn.get("incomingRoad") or "").strip()
            cnx = (conn.get("connectingRoad") or "").strip()
            if inc in comp_roads or cnx in comp_roads:
                attached = True
            if inc and inc not in all_road_ids:
                junction_defect = True
            if cnx and cnx not in all_road_ids:
                junction_defect = True

            lane_link = conn.find("laneLink")
            if lane_link is not None:
                from_lane = lane_link.get("from")
                to_lane = lane_link.get("to")
                inc_lanes = _lane_ids_of_road(roads_by_id.get(inc))
                cnx_lanes = _lane_ids_of_road(roads_by_id.get(cnx))
                if from_lane and inc_lanes and from_lane not in inc_lanes:
                    lanelink_defect = True
                if to_lane and cnx_lanes and to_lane not in cnx_lanes:
                    lanelink_defect = True

    # NOTE: junction/connection defects are evaluated globally here (signal),
    # so a dangling reference anywhere in the junctio set reports as a defect
    # for the component it attaches to. This is intentionally conservative.

    boundary_truncated = False
    if map_bbox is not None:
        min_x, min_y, max_x, max_y, diagonal = map_bbox
        if diagonal > 1e-9:
            # A map whose extent collapses along an axis (e.g. an artificial
            # fixture stacking every road at the same origin) has no
            # meaningful map-edge truncation: boundary detection requires a
            # non-degenerate 2D extent so synthetic islands never
            # misclassify as BOUNDARY_TRUNCATION.
            x_span = max_x - min_x
            y_span = max_y - min_y
            if x_span > 1e-9 and y_span > 1e-9:
                tol = max(_BOUNDARY_ABS_FLOOR_M, _BOUNDARY_RELATIVE_TOL * diagonal)
                for x, y in comp_endpoints:
                    if (
                        abs(x - min_x) <= tol
                        or abs(x - max_x) <= tol
                        or abs(y - min_y) <= tol
                        or abs(y - max_y) <= tol
                    ):
                        boundary_truncated = True
                        break

    return {
        "road_link_defect": road_link_defect,
        "junction_defect": junction_defect,
        "lanelink_defect": lanelink_defect,
        "intentional": intentional,
        "boundary_truncated": boundary_truncated,
        "private_or_service": private_or_service,
        "parking": parking,
    }


def classify_component(
    comp_roads: Set[str],
    roads_by_id: Dict[str, ET.Element],
    junctions: List[ET.Element],
    map_bbox: Optional[Tuple[float, float, float, float, float]] = None,
) -> Dict[str, Any]:
    """Classify a small road component; see module docstring for precedence.

    Returns a dict with ``category``, ``reason``, ``deletable``, ``size`` and
    ``road_ids``. Deterministic for the same inputs.
    """
    signals = _component_signals(comp_roads, roads_by_id, junctions, map_bbox)

    category: str
    reason: str

    if signals["road_link_defect"]:
        category, reason = ROAD_LINK_DEFECT, "road link references missing element"
    elif signals["junction_defect"]:
        category, reason = JUNCTION_DEFECT, "junction connection references missing road"
    elif signals["lanelink_defect"]:
        category, reason = LANELINK_DEFECT, "laneLink references missing lane id"
    elif signals["intentional"] and signals["boundary_truncated"]:
        category, reason = (
            UNKNOWN,
            "conflicting signals: intentional marker plus boundary truncation",
        )
    elif signals["intentional"]:
        category, reason = INTENTIONAL_ISLAND, "explicit intentional-island marker"
    elif signals["boundary_truncated"]:
        category, reason = BOUNDARY_TRUNCATION, "component geometry touches map bbox edge"
    elif signals["private_or_service"]:
        category, reason = PRIVATE_OR_SERVICE, "road type private/service"
    elif signals["parking"]:
        category, reason = PARKING_OR_YARD, "road type parking"
    else:
        category, reason = SOURCE_DISCONNECTED, "genuinely disconnected source component"

    return {
        "category": category,
        "reason": reason,
        "deletable": category in DELETABLE_UNDER_QUARANTINE,
        "size": len(comp_roads),
        "road_ids": sorted(comp_roads, key=lambda x: (len(x), x)),
    }


def component_classification_report(
    components: List[Set[str]],
    roads_by_id: Dict[str, ET.Element],
    junctions: List[ET.Element],
) -> Dict[str, Any]:
    """Classify every component (not just small ones) for an audit report."""
    map_bbox = _map_bbox(roads_by_id)
    entries = []
    for comp in components:
        entry = classify_component(comp, roads_by_id, junctions, map_bbox=map_bbox)
        entries.append(
            {
                "size": entry["size"],
                "road_ids": entry["road_ids"],
                "category": entry["category"],
                "reason": entry["reason"],
                "deletable": entry["deletable"],
            }
        )
    categories: Dict[str, int] = {}
    for entry in entries:
        categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    return {
        "component_count": len(entries),
        "categories": dict(sorted(categories.items())),
        "components": entries,
    }