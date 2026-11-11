"""RQ3 "same-place" auto-map-of-record -> manual Grid0828 footprint crop.

Pure SUBSET derivation of the auto map-of-record: keep exactly the roads and
junctions that fall inside the manual Grid0828 footprint (plus an optional
buffer), and remove every reference that the subset makes dangling. This
module performs NO geometry/lane/elevation edits and NO repair -- every byte
that survives in a kept `<road>`/`<junction>` is an unmodified clone of the
source; the only mutations are element REMOVALS of now-dangling links, exactly
as required to keep the output self-consistent (AGENTS: generator fixes at
source stage only; no final-XODR cosmetic mutation -- this is neither: it is a
derived, self-consistent SUBSET, not an edit of the frozen map-of-record).

Important: a nonzero ``sampling_fallback_count`` means at least one road
primitive was unsupported/malformed and fell back to the anchor point.
This drops coverage and is FATAL for admission -- the report status must be
FAIL, never a clean PASS. The hard check ``zero_sampling_fallbacks``
(sampling_fallback_count == 0) is one of eight conditions that must all
hold for a PASS verdict.

Frames and the hull-footprint polygon are entirely delegated to
``ultimate_pipeline.domain_gap.local_registration`` (RQ1's already-verified
auto<->manual registration); this module owns only the SUBSET/link-closure
rules below, documented in the order they are applied:

a) Footprint polygon: convex hull of the manual map's planView geometry
   points, transformed into the auto map's local frame
   (``local_registration.manual_geometry_convex_hull`` +
   ``transform_manual_points_to_auto_local``), then optionally dilated by
   ``buffer_m`` (shapely ``Polygon.buffer``, >=0 only -- a negative buffer
   would erode the footprint rather than widen it, which is never the intent
   here and is rejected).
   Boundary semantics: "inside" is tested throughout this module with
   shapely's ``Polygon.contains``/``prepared.contains``, which is
   boundary-EXCLUSIVE -- a point lying exactly ON the hull (or buffered-hull)
   boundary is NOT considered inside and will not by itself cause a road to
   be kept. This only matters for degenerate/exact-touch geometry (a sampled
   point landing precisely on the hull edge); any ``buffer_m > 0`` moves the
   boundary away from the hull's own vertices and makes an exact-touch case
   vanishingly unlikely in practice.

b) Road selection (non-junction roads, ``road[@junction='-1']`` only --
   junction-member roads are governed entirely by rule (c), never by this
   per-road test):
     - ``selection="any_point"`` (default): a road is kept iff ANY point
       sampled along ANY of its ``<planView><geometry>`` primitives (using the
       canonical, paramPoly3/spiral-aware kernel,
       ``opendrive_geometry_kernel.sample``) lies inside the footprint
       polygon. This is deliberately curve-aware: a paramPoly3 road whose
       stored anchor point (``x``,``y``) and whose polyline-of-geometry-
       anchors are both outside the polygon, but whose actual curved
       centerline swings through it, is still kept. A cheap, EXACT (not
       heuristic) pre-filter skips the expensive per-geometry sampling when
       the primitive's stored (x, y) anchor is farther from the polygon's
       bounding box than the primitive's own `length` -- since arc length is
       an upper bound on displacement from the start point for every
       supported primitive (line/arc/poly3/paramPoly3/spiral), this can never
       incorrectly discard a candidate.
     - ``selection="centroid"``: legacy/cheaper rule matching
       ``local_registration.road_centroid`` -- kept iff the mean of the
       road's stored ``<geometry x y>`` anchor points lies inside the
       polygon. Coarser and NOT curve-aware (a curved road can be kept/
       dropped differently than under "any_point"); kept only for parity/
       comparison with RQ1's existing crop rule.

c) Junction closure: a junction is KEPT iff, after discarding any of its own
   ``<connection>`` elements whose ``incomingRoad`` or ``connectingRoad`` id
   is ABSENT from the auto map entirely (a pre-existing data-integrity
   defect, independent of this crop -- counted as ``connections_removed_dangling``),
   at least one valid connection remains AND every remaining valid
   connection's ``incomingRoad`` is itself a kept road. Resolved to a fixed
   point (not a single pass) so nested junctions -- where one junction's
   incoming road is itself a connecting-road member of another junction --
   converge correctly regardless of which junction is evaluated first.  Once
   a junction is kept, ALL roads with ``@junction`` equal to that junction's
   id are kept (never partially -- a connecting road is never kept without
   its owning junction, and never dropped while its junction survives).
   Junctions that are not kept are dropped entirely, together with every one
   of their connecting roads.

d) Link consistency (applied only to the roads/junctions kept by (b)/(c)):
     - Road-level ``<link><predecessor/successor elementType="road" ...>``
       pointing at a road that was not kept is REMOVED (count by slot).
     - Road-level ``<link><predecessor/successor elementType="junction" ...>``
       pointing at a junction that was not kept is REMOVED (count by slot).
     - The lane-level link in the boundary laneSection affected by a removed
       road-level link (the FIRST laneSection for a removed predecessor, the
       LAST for a removed successor -- the only laneSections whose lane
       ``<link>`` can possibly reference a different road) has its matching
       ``predecessor``/``successor`` child removed too (count by slot).
       Intra-road lane links between a road's own laneSections are never
       touched -- they never reference another road.
     - Defensive/non-standard-dialect support: if any ``<lane><link>`` child
       carries an explicit ``road`` attribute (as produced by some internal
       tiling representations -- see ``tiling/tile_extractor.py``'s
       ``_drop_links_outside_tile``) naming a road that was not kept, it is
       removed too, counted separately (``lane_link_explicit_road_removed``).
     - This can never add or invent a link -- only remove ones that would
       otherwise dangle.

e) Header is a byte-identical deep copy of the source ``<header>`` (geoReference,
   offset, revMajor/Minor, etc. untouched). Top-level ``<controller>``
   elements are first copied byte-faithfully (document order) into the
   output, then pruned in place: a ``<control signalId=...>`` child is
   removed if it no longer resolves to a ``<signal>`` on a kept road
   (signals are scanned map-wide by id, independent of which road currently
   owns them; count ``controller_controls_removed``). A controller that is
   left with zero ``<control>`` children AFTER pruning is dropped entirely
   (count ``controllers_dropped_zero_controls``) -- but ONLY if it
   originally had at least one ``<control>`` child; a controller that was
   ALREADY empty of ``<control>`` children in the source (a legal, if
   unusual, document) is never dropped by this rule and is preserved
   untouched (count ``controllers_empty_preserved``). A ``<junction>``'s own
   ``<controller id=.../>`` reference (grouping hint toward a top-level
   controller) is removed if the controller it names was dropped (count
   ``junction_controller_ref_removed``). ``<signal>``/``<object>`` elements
   need no special handling: they are children of ``<road>`` and therefore
   survive or drop automatically with their owning road.

g) Any other top-level ``OpenDRIVE`` child kind this module has no dedicated
   reference-aware rule for (e.g. ``junctionGroup``, ``station``,
   ``userData``, ``include``) is preserved byte-faithfully and
   unconditionally -- this module's selection/closure rules (b)/(c) are
   scoped to roads and junctions only, so an unknown top-level kind carries
   no reference this module could validate or invalidate, and dropping it
   silently would violate the "pure SUBSET" contract. Every top-level tag
   seen in the input is accounted for in the report's
   ``top_level_accounting`` (``input_count``/``kept_count``/
   ``dropped_count`` per tag); for every handled kind
   ``kept_count + dropped_count == input_count`` by construction, and for
   every unknown kind ``dropped_count`` is always 0.

f) Determinism: every kept element is emitted in the SAME relative order it
   had in the source document (filter-by-membership-test over
   ``root.findall(...)``, never an unordered ``set``/``dict`` iteration for
   the final tree). Given byte-identical inputs and arguments, the output is
   byte-identical. No timestamp or other non-deterministic value is ever
   written into the XODR tree itself (timestamps belong only in the caller's
   manifest).
"""
from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.domain_gap.local_registration import (
    manual_geometry_convex_hull,
    read_georef_proj4,
    read_offset,
    road_centroid,
    transform_manual_points_to_auto_local,
)
from ultimate_pipeline.geometry.opendrive_geometry_kernel import sample as kernel_sample

SELECTION_MODES: Tuple[str, ...] = ("any_point", "centroid")
DEFAULT_SAMPLE_SPACING_M = 2.0


# ------------------------------------------------------------------ polygon
def build_footprint_polygon(
    auto_root: ET.Element,
    manual_root: ET.Element,
    *,
    buffer_m: float = 0.0,
) -> Polygon:
    """Manual convex hull -> auto-local polygon, optionally buffered.

    See module docstring (a). ``buffer_m`` must be >= 0.
    """
    if not math.isfinite(buffer_m) or buffer_m < 0.0:
        raise ValueError(f"buffer_m must be a finite number >= 0, got {buffer_m!r}")

    auto_off = read_offset(auto_root)
    auto_proj = read_georef_proj4(auto_root)
    manual_proj = read_georef_proj4(manual_root)
    hull_pts = manual_geometry_convex_hull(manual_root)
    poly = transform_manual_points_to_auto_local(hull_pts, manual_proj, auto_proj, auto_off)
    if buffer_m > 0.0:
        poly = poly.buffer(buffer_m)
    if poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(
            f"footprint polygon degenerated to {poly.geom_type!r} after buffering; "
            "cannot crop against a non-area footprint"
        )
    return poly


def _dist_point_to_bbox(x: float, y: float, bounds: Tuple[float, float, float, float]) -> float:
    minx, miny, maxx, maxy = bounds
    dx = max(minx - x, 0.0, x - maxx)
    dy = max(miny - y, 0.0, y - maxy)
    return math.hypot(dx, dy)


def _road_length_m(road: ET.Element) -> float:
    total = 0.0
    for g in road.findall("./planView/geometry"):
        total += _safe_float(g.get("length", "0"), 0.0)
    return total


# ------------------------------------------------------------------ road selection (rule b)
def _road_matches_any_point(
    road: ET.Element,
    prepared_polygon,
    polygon_bounds: Tuple[float, float, float, float],
    spacing: float,
) -> Tuple[bool, int]:
    """Returns (matched, sampling_fallback_count)."""
    fallbacks = 0
    for g in road.findall("./planView/geometry"):
        x0 = _safe_float(g.get("x", "0"), 0.0)
        y0 = _safe_float(g.get("y", "0"), 0.0)
        length = _safe_float(g.get("length", "0"), 0.0)
        # Exact (non-heuristic) pre-filter: arc length upper-bounds displacement
        # from the start point for every supported primitive kind.
        if _dist_point_to_bbox(x0, y0, polygon_bounds) > length + 1e-6:
            continue
        try:
            points = kernel_sample(g, spacing)
            coords = [(p.x, p.y) for p in points]
        except Exception:
            # Unsupported/malformed primitive: never silently drop coverage --
            # fall back to the one point we do have (the stored anchor).
            fallbacks += 1
            coords = [(x0, y0)]
        for (x, y) in coords:
            if prepared_polygon.contains(Point(x, y)):
                return True, fallbacks
    return False, fallbacks


def select_non_junction_roads(
    auto_root: ET.Element,
    polygon: Polygon,
    *,
    selection: str = "any_point",
    sample_spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
) -> Tuple[List[ET.Element], int]:
    """Rule (b). Returns (kept roads in document order, sampling_fallback_count)."""
    if selection not in SELECTION_MODES:
        raise ValueError(f"selection must be one of {SELECTION_MODES}, got {selection!r}")
    pp = prep(polygon)
    bounds = polygon.bounds
    kept: List[ET.Element] = []
    fallbacks = 0
    for road in auto_root.findall("road"):
        if road.get("junction", "-1") not in ("-1", None, ""):
            continue
        if selection == "centroid":
            c = road_centroid(road)
            if c is not None and pp.contains(Point(c)):
                kept.append(road)
        else:
            matched, fb = _road_matches_any_point(road, pp, bounds, sample_spacing_m)
            fallbacks += fb
            if matched:
                kept.append(road)
    return kept, fallbacks


# ------------------------------------------------------------------ junction closure (rule c)
def resolve_junction_closure(
    auto_root: ET.Element,
    kept_non_junction_road_ids: Set[str],
) -> Tuple[Set[str], Set[str], Dict[str, str], int]:
    """Rule (c). Returns (kept_junction_ids, connecting_road_ids,
    dropped_junction_reasons, connections_removed_dangling_count).
    """
    all_road_ids: Set[str] = {r.get("id") for r in auto_root.findall("road") if r.get("id")}
    roads_by_junction: Dict[str, List[str]] = {}
    for r in auto_root.findall("road"):
        jid = r.get("junction", "-1")
        rid = r.get("id")
        if jid not in ("-1", None, "") and rid:
            roads_by_junction.setdefault(jid, []).append(rid)

    junctions_in_order = [j for j in auto_root.findall("junction") if j.get("id")]
    pending: Dict[str, ET.Element] = {j.get("id"): j for j in junctions_in_order}

    kept_road_ids: Set[str] = set(kept_non_junction_road_ids)
    kept_junction_ids: Set[str] = set()
    dropped_reasons: Dict[str, str] = {}
    connections_removed_dangling = 0

    changed = True
    while changed:
        changed = False
        for jid in list(pending.keys()):
            j = pending[jid]
            connections = list(j.findall("connection"))
            if not connections:
                dropped_reasons[jid] = "no_connections"
                del pending[jid]
                changed = True
                continue

            valid_connections = []
            dangling_here = 0
            for c in connections:
                inc = c.get("incomingRoad")
                conn_rd = c.get("connectingRoad")
                if inc not in all_road_ids or conn_rd not in all_road_ids:
                    dangling_here += 1
                    continue
                valid_connections.append(c)

            if not valid_connections:
                connections_removed_dangling += dangling_here
                dropped_reasons[jid] = "zero_valid_connections_after_dangling_removal"
                del pending[jid]
                changed = True
                continue

            all_incoming_kept = all(c.get("incomingRoad") in kept_road_ids for c in valid_connections)
            if all_incoming_kept:
                connections_removed_dangling += dangling_here
                kept_junction_ids.add(jid)
                kept_road_ids.update(roads_by_junction.get(jid, []))
                del pending[jid]
                changed = True
            # else: leave pending; may become valid once a nested junction
            # it depends on is decided in a later pass.

    for jid in pending:
        dropped_reasons[jid] = "incoming_road_not_in_footprint"

    connecting_road_ids = {
        rid for jid in kept_junction_ids for rid in roads_by_junction.get(jid, [])
    }
    return kept_junction_ids, connecting_road_ids, dropped_reasons, connections_removed_dangling


# ------------------------------------------------------------------ link consistency (rule d)
def _lane_sections_in_order(road: ET.Element) -> List[ET.Element]:
    lanes = road.find("lanes")
    if lanes is None:
        return []
    sections = list(lanes.findall("laneSection"))
    sections.sort(key=lambda ls: _safe_float(ls.get("s", "0"), 0.0))
    return sections


def _drop_boundary_lane_links(road: ET.Element, slot: str, counts: Dict[str, int]) -> None:
    sections = _lane_sections_in_order(road)
    if not sections:
        return
    boundary = sections[0] if slot == "predecessor" else sections[-1]
    key = f"lane_link_boundary_{slot}_removed"
    for lane in boundary.findall(".//lane"):
        link = lane.find("link")
        if link is None:
            continue
        target = link.find(slot)
        if target is not None:
            link.remove(target)
            counts[key] = counts.get(key, 0) + 1


def _drop_explicit_road_lane_links(road: ET.Element, kept_road_ids: Set[str], counts: Dict[str, int]) -> None:
    """Defensive, non-standard-dialect support (see tile_extractor.py)."""
    for lane in road.findall(".//lane"):
        link = lane.find("link")
        if link is None:
            continue
        for slot in ("predecessor", "successor"):
            elem = link.find(slot)
            if elem is None:
                continue
            ref_road = elem.get("road")
            if ref_road and ref_road not in kept_road_ids:
                link.remove(elem)
                counts["lane_link_explicit_road_removed"] = counts.get("lane_link_explicit_road_removed", 0) + 1


def apply_link_consistency(
    kept_roads: Sequence[ET.Element],
    kept_road_ids: Set[str],
    kept_junction_ids: Set[str],
) -> Dict[str, int]:
    """Rule (d), mutating the (already-cloned) `kept_roads` in place."""
    counts: Dict[str, int] = {}
    for road in kept_roads:
        link = road.find("link")
        if link is not None:
            for slot in ("predecessor", "successor"):
                elem = link.find(slot)
                if elem is None:
                    continue
                etype = elem.get("elementType")
                eid = elem.get("elementId")
                drop = False
                if etype == "road" and eid not in kept_road_ids:
                    drop = True
                elif etype == "junction" and eid not in kept_junction_ids:
                    drop = True
                if drop:
                    link.remove(elem)
                    key = f"road_link_{slot}_removed"
                    counts[key] = counts.get(key, 0) + 1
                    _drop_boundary_lane_links(road, slot, counts)
        _drop_explicit_road_lane_links(road, kept_road_ids, counts)
    return counts


def apply_connection_pruning(
    kept_junctions: Sequence[ET.Element],
    kept_road_ids: Set[str],
) -> int:
    """Remove any surviving `<connection>` (already-cloned junctions) whose
    incomingRoad/connectingRoad fell outside the final kept-road set. Given
    `resolve_junction_closure`'s guarantees this should normally remove
    nothing; kept defensively so the output's own dangling-check always
    passes even under future changes to the closure logic above.
    """
    removed = 0
    for j in kept_junctions:
        for c in list(j.findall("connection")):
            inc = c.get("incomingRoad")
            conn_rd = c.get("connectingRoad")
            if inc not in kept_road_ids or conn_rd not in kept_road_ids:
                j.remove(c)
                removed += 1
    return removed


# ------------------------------------------------------------------ controllers (rule e)
def apply_controller_pruning(
    cropped_root: ET.Element,
    kept_road_ids: Set[str],
) -> Tuple[Dict[str, int], Set[str]]:
    """Rule (e). Mutates the already-copied top-level ``<controller>``
    elements of ``cropped_root`` in place. Returns ``(counts,
    dropped_controller_ids)`` -- the latter feeds
    ``apply_junction_controller_ref_pruning`` below.
    """
    signal_owner: Dict[str, str] = {}
    for road in cropped_root.findall("road"):
        rid = road.get("id")
        for sig in road.findall(".//signal"):
            sid = sig.get("id")
            if sid:
                signal_owner[sid] = rid

    counts = {
        "controller_controls_removed": 0,
        "controllers_dropped_zero_controls": 0,
        "controllers_empty_preserved": 0,
    }
    dropped_controller_ids: Set[str] = set()
    for controller in list(cropped_root.findall("controller")):
        originally_had_controls = bool(controller.findall("control"))
        for control in list(controller.findall("control")):
            sid = control.get("signalId")
            owner = signal_owner.get(sid)
            if owner is None or owner not in kept_road_ids:
                controller.remove(control)
                counts["controller_controls_removed"] += 1
        if not controller.findall("control"):
            if originally_had_controls:
                cid = controller.get("id")
                cropped_root.remove(controller)
                counts["controllers_dropped_zero_controls"] += 1
                if cid:
                    dropped_controller_ids.add(cid)
            else:
                # Originally empty -- rule (e) only removes DANGLING
                # references, it never deletes a controller that carried
                # none to begin with.
                counts["controllers_empty_preserved"] += 1
    return counts, dropped_controller_ids


def apply_junction_controller_ref_pruning(
    kept_junctions: Sequence[ET.Element],
    dropped_controller_ids: Set[str],
) -> int:
    """Rule (e) continued: a ``<junction><controller id=.../>`` grouping
    reference that names a top-level controller dropped by
    ``apply_controller_pruning`` would otherwise dangle; it is removed
    (count returned, by caller convention merged into
    ``junction_controller_ref_removed``)."""
    removed = 0
    for junction in kept_junctions:
        for ref in list(junction.findall("controller")):
            cid = ref.get("id")
            if cid in dropped_controller_ids:
                junction.remove(ref)
                removed += 1
    return removed


# ------------------------------------------------------------------ dangling-reference proof
def find_dangling_references(cropped_root: ET.Element) -> Dict[str, List[Dict[str, Any]]]:
    """Independent, from-scratch proof that the OUTPUT tree carries zero
    dangling road/lane/junction references. Used as a hard post-build check
    (never relaxed/ignored; see `validate_cropped_root`)."""
    road_ids = {r.get("id") for r in cropped_root.findall("road") if r.get("id")}
    junction_ids = {j.get("id") for j in cropped_root.findall("junction") if j.get("id")}

    dangling: Dict[str, List[Dict[str, Any]]] = {
        "road_link": [],
        "junction_connection": [],
        "lane_link_explicit_road": [],
    }

    for road in cropped_root.findall("road"):
        rid = road.get("id")
        link = road.find("link")
        if link is not None:
            for slot in ("predecessor", "successor"):
                elem = link.find(slot)
                if elem is None:
                    continue
                etype, eid = elem.get("elementType"), elem.get("elementId")
                if etype == "road" and eid not in road_ids:
                    dangling["road_link"].append({"road_id": rid, "slot": slot, "target": eid, "elementType": etype})
                elif etype == "junction" and eid not in junction_ids:
                    dangling["road_link"].append({"road_id": rid, "slot": slot, "target": eid, "elementType": etype})
        for lane in road.findall(".//lane"):
            lane_link = lane.find("link")
            if lane_link is None:
                continue
            for slot in ("predecessor", "successor"):
                elem = lane_link.find(slot)
                if elem is None:
                    continue
                ref_road = elem.get("road")
                if ref_road and ref_road not in road_ids:
                    dangling["lane_link_explicit_road"].append(
                        {"road_id": rid, "slot": slot, "target": ref_road}
                    )

    for junction in cropped_root.findall("junction"):
        jid = junction.get("id")
        for c in junction.findall("connection"):
            inc, conn_rd = c.get("incomingRoad"), c.get("connectingRoad")
            if inc not in road_ids or conn_rd not in road_ids:
                dangling["junction_connection"].append(
                    {"junction_id": jid, "connection_id": c.get("id"), "incomingRoad": inc, "connectingRoad": conn_rd}
                )

    return dangling


def find_unresolved_controller_references(cropped_root: ET.Element) -> Dict[str, List[Dict[str, Any]]]:
    """Independent, from-scratch proof (companion to
    `find_dangling_references`) that the OUTPUT tree carries zero unresolved
    controller references: every top-level ``<controller><control
    signalId=.../>`` must resolve to a ``<signal id=.../>`` that exists
    under some ``<road>`` in the output, and every ``<junction><controller
    id=.../>`` grouping reference must resolve to a top-level
    ``<controller id=...>`` present in the output."""
    signal_ids: Set[str] = set()
    for road in cropped_root.findall("road"):
        for sig in road.findall(".//signal"):
            sid = sig.get("id")
            if sid:
                signal_ids.add(sid)
    controller_ids: Set[str] = {c.get("id") for c in cropped_root.findall("controller") if c.get("id")}

    unresolved: Dict[str, List[Dict[str, Any]]] = {
        "control_signal": [],
        "junction_controller_ref": [],
    }
    for controller in cropped_root.findall("controller"):
        cid = controller.get("id")
        for control in controller.findall("control"):
            sid = control.get("signalId")
            if sid not in signal_ids:
                unresolved["control_signal"].append({"controller_id": cid, "signalId": sid})
    for junction in cropped_root.findall("junction"):
        jid = junction.get("id")
        for ref in junction.findall("controller"):
            cid = ref.get("id")
            if cid not in controller_ids:
                unresolved["junction_controller_ref"].append({"junction_id": jid, "controller_id": cid})
    return unresolved


# ------------------------------------------------------------------ top-level API
def crop_auto_to_manual_footprint(
    auto_root: ET.Element,
    manual_root: ET.Element,
    *,
    buffer_m: float = 0.0,
    selection: str = "any_point",
    sample_spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
) -> Tuple[ET.Element, Dict[str, Any]]:
    """Pure SUBSET derivation (see module docstring for the full rule set a-f).

    Returns ``(cropped_root, report)``. `auto_root`/`manual_root` are never
    mutated; `cropped_root` is a freshly built tree of deep clones.
    """
    if selection not in SELECTION_MODES:
        raise ValueError(f"selection must be one of {SELECTION_MODES}, got {selection!r}")

    polygon = build_footprint_polygon(auto_root, manual_root, buffer_m=buffer_m)

    non_junction_roads_total = sum(
        1 for r in auto_root.findall("road") if r.get("junction", "-1") in ("-1", None, "")
    )
    auto_roads_total = len(auto_root.findall("road"))
    junctions_total = len(auto_root.findall("junction"))

    kept_normal_roads, sampling_fallbacks = select_non_junction_roads(
        auto_root, polygon, selection=selection, sample_spacing_m=sample_spacing_m
    )
    kept_normal_ids = {r.get("id") for r in kept_normal_roads if r.get("id")}

    kept_junction_ids, connecting_road_ids, dropped_junction_reasons, conn_dangling = (
        resolve_junction_closure(auto_root, kept_normal_ids)
    )
    kept_road_ids = kept_normal_ids | connecting_road_ids

    # Build the output tree, preserving original document order throughout.
    cropped_root = ET.Element("OpenDRIVE")
    header = auto_root.find("header")
    cropped_root.append(copy.deepcopy(header) if header is not None else ET.Element("header"))

    kept_roads_clone: List[ET.Element] = []
    road_length_kept = 0.0
    road_length_dropped = 0.0
    for road in auto_root.findall("road"):
        rid = road.get("id")
        length = _road_length_m(road)
        if rid in kept_road_ids:
            clone = copy.deepcopy(road)
            cropped_root.append(clone)
            kept_roads_clone.append(clone)
            road_length_kept += length
        else:
            road_length_dropped += length

    kept_junctions_clone: List[ET.Element] = []
    for junction in auto_root.findall("junction"):
        jid = junction.get("id")
        if jid in kept_junction_ids:
            clone = copy.deepcopy(junction)
            cropped_root.append(clone)
            kept_junctions_clone.append(clone)

    # Top-level <controller> elements (rule e): copied byte-faithfully in
    # document order; pruned in place below.
    for controller in auto_root.findall("controller"):
        cropped_root.append(copy.deepcopy(controller))

    # Rule (g): any other top-level OpenDRIVE child kind this module has no
    # dedicated reference-aware rule for is preserved byte-faithfully and
    # unconditionally (never silently dropped).
    _HANDLED_TOP_LEVEL_TAGS = {"header", "road", "junction", "controller"}
    unknown_top_level_preserved: Dict[str, int] = {}
    for child in auto_root:
        if child.tag in _HANDLED_TOP_LEVEL_TAGS:
            continue
        cropped_root.append(copy.deepcopy(child))
        unknown_top_level_preserved[child.tag] = unknown_top_level_preserved.get(child.tag, 0) + 1

    link_counts = apply_link_consistency(kept_roads_clone, kept_road_ids, kept_junction_ids)
    extra_conn_removed = apply_connection_pruning(kept_junctions_clone, kept_road_ids)
    controller_counts, dropped_controller_ids = apply_controller_pruning(cropped_root, kept_road_ids)
    junction_controller_refs_removed = apply_junction_controller_ref_pruning(
        kept_junctions_clone, dropped_controller_ids
    )

    dangling = find_dangling_references(cropped_root)
    dangling_total = sum(len(v) for v in dangling.values())
    unresolved_controller_refs = find_unresolved_controller_references(cropped_root)
    unresolved_controller_refs_total = sum(len(v) for v in unresolved_controller_refs.values())

    # Rule (g) accounting: every top-level tag seen in the input must be
    # accounted for as kept + dropped == input, independent of which rule
    # (specific or the generic unknown-kind fallback) handled it.
    top_level_input_counts: Dict[str, int] = {}
    for child in auto_root:
        top_level_input_counts[child.tag] = top_level_input_counts.get(child.tag, 0) + 1
    top_level_accounting: Dict[str, Dict[str, int]] = {}
    for tag, input_count in top_level_input_counts.items():
        kept_count = len(cropped_root.findall(tag))
        top_level_accounting[tag] = {
            "input_count": input_count,
            "kept_count": kept_count,
            "dropped_count": input_count - kept_count,
        }

    counts: Dict[str, Any] = {
        "auto_roads_total": auto_roads_total,
        "auto_roads_non_junction_total": non_junction_roads_total,
        "auto_roads_junction_member_total": auto_roads_total - non_junction_roads_total,
        "roads_kept_non_junction": len(kept_normal_roads),
        "roads_kept_junction_connecting": len(connecting_road_ids),
        "roads_kept_total": len(kept_road_ids),
        "roads_dropped_total": auto_roads_total - len(kept_road_ids),
        "road_length_kept_m": round(road_length_kept, 3),
        "road_length_dropped_m": round(road_length_dropped, 3),
        "junctions_total": junctions_total,
        "junctions_kept": len(kept_junction_ids),
        "junctions_dropped": junctions_total - len(kept_junction_ids),
        "connections_removed_dangling": conn_dangling + extra_conn_removed,
        "controllers_total": len(auto_root.findall("controller")),
        "controllers_kept": len(cropped_root.findall("controller")),
        "junction_controller_ref_removed": junction_controller_refs_removed,
        "top_level_unknown_tags_preserved": unknown_top_level_preserved,
        "sampling_fallback_count": sampling_fallbacks,
        "dangling_references_found": dangling_total,
        "unresolved_controller_references_found": unresolved_controller_refs_total,
    }
    counts.update(link_counts)
    counts.update(controller_counts)

    report: Dict[str, Any] = {
        "schema": "footprint_crop/v1",
        "selection": selection,
        "buffer_m": buffer_m,
        "sample_spacing_m": sample_spacing_m,
        "polygon_wkt": polygon.wkt,
        "polygon_bounds_auto_local": list(polygon.bounds),
        "counts": counts,
        "junctions_dropped_reasons": dropped_junction_reasons,
        "dangling_references": dangling,
        "unresolved_controller_references": unresolved_controller_refs,
        "top_level_accounting": top_level_accounting,
    }
    return cropped_root, report
