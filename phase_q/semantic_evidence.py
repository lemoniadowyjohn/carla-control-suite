"""Q3 - Full semantic source/runtime/package equivalence.

Structural equivalence (roads/junctions/lane sections/driving lanes) is already
proven.  This module extends equivalence to perception semantics:

  signals, signal references, controllers, objects, crosswalk objects,
  speed limits, road types, road markings, lane-change permissions,
  turn-lane semantics, stop/yield controls, sidewalks, pedestrian lanes,
  traffic-light actor bindings, semantic material classes.

Each extractor yields exact ID sets (not only counts).  Comparison output is
per-category missing/unexpected ID sets across artifact pairs.

Artifact sides:

  source     - accepted source/enrichment candidate (Phase H output)
  repaired   - governed repaired candidate
  payload    - actual CARLA load payload (governed payload artifact, Q4)
  runtime    - runtime to_opendrive() dump
  packaged   - cooked package OpenDRIVE
  actors     - spawned runtime actors (requires packaged map; fail-closed)
  labels     - sensor semantic labels (requires captures; fail-closed)
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from phase_q.common import XodrTree, norm_id, safe_float

CATEGORIES = [
    "signals",
    "signal_references",
    "controllers",
    "objects",
    "crosswalk_objects",
    "speed_limits",
    "road_types",
    "road_markings",
    "lane_change_permissions",
    "turn_lane_semantics",
    "stop_yield_controls",
    "sidewalks",
    "pedestrian_lanes",
    "traffic_light_actor_bindings",
    "semantic_material_classes",
]

# Categories that can only be produced by packaged/runtime artifacts.
RUNTIME_ONLY_CATEGORIES = ("traffic_light_actor_bindings",)

# Categories that are decisive for the PERCEPTION_RELEASE verdict.
PERCEPTION_DECISIVE = frozenset({
    "signals", "signal_references", "controllers", "objects",
    "crosswalk_objects", "speed_limits", "road_markings",
    "lane_change_permissions", "turn_lane_semantics", "stop_yield_controls",
    "sidewalks", "pedestrian_lanes", "semantic_material_classes",
})

_TAG_RE = re.compile(r"\{[^}]*\}")


def _el_attr(el: Any, name: str, default: str = "") -> str:
    if el is None:
        return default
    v = el.get(name)
    return norm_id(v) if v is not None else default


def _type_attr(el: Any) -> str:
    return _el_attr(el, "type").lower()


def _lane_of(road_el: Any, lane_el: Any) -> str:
    rid = _el_attr(road_el, "id")
    sid = _el_attr(road_el.find("laneSection"), "s")
    return "{}/{}".format(rid, _el_attr(lane_el, "id"))


def extract_semantic_inventory(xodr_text: str) -> Dict[str, Set[str]]:
    """Extract exact semantic ID sets from one OpenDRIVE artifact."""
    inv: Dict[str, Set[str]] = {c: set() for c in CATEGORIES}
    tree = XodrTree(xodr_text)
    root = tree.root

    for sig in root.iter("signal"):
        sig_id = _el_attr(sig, "id")
        s_type = _type_attr(sig)
        s_sub = _el_attr(sig, "subtype").lower()
        inv["signals"].add(sig_id)
        if s_type == "r" and s_sub in ("274", "292", "263"):
            inv["speed_limits"].add(sig_id)
        if s_type == "r" and s_sub in ("205", "206", "207"):
            inv["stop_yield_controls"].add(sig_id)
        if s_type in ("1000001", "1000002"):
            inv["traffic_light_actor_bindings"].add(sig_id)

    for ref in root.iter("signalReference"):
        inv["signal_references"].add(_el_attr(ref, "id"))

    for ctrl in root.iter("controller"):
        inv["controllers"].add(_el_attr(ctrl, "id"))
        ctrl_id = _el_attr(ctrl, "id")
        for ctrl_sig in ctrl.iter("signal"):
            inv["traffic_light_actor_bindings"].add("{}/{}".format(ctrl_id, _el_attr(ctrl_sig, "ref")))

    for obj in root.iter("object"):
        o_id = _el_attr(obj, "id")
        o_type = _type_attr(obj)
        o_sub = _el_attr(obj, "subtype").lower()
        inv["objects"].add(o_id)
        if o_type in ("crosswalk", "crosswalk zone", "crosswalkzone") or o_sub in ("crosswalk", "zebra"):
            inv["crosswalk_objects"].add(o_id)
        if o_type in ("pedestrianarea", "pedestrian area", "pedestrian_area"):
            inv["pedestrian_lanes"].add(o_id)
        for mat in obj.iter("material"):
            inv["semantic_material_classes"].add("{}/{}".format(o_id, _el_attr(mat, "name") or _el_attr(mat, "s")))

    for road in root.iter("road"):
        rid = _el_attr(road, "id")
        for t in road.iter("type"):
            if t.tag.split("}")[-1] != "type":
                continue
            inv["road_types"].add("{}/{}".format(rid, _el_attr(t, "type")))

        for lane in road.iter("lane"):
            lid = _el_attr(lane, "id")
            lane_type = _el_attr(lane, "type")
            lane_key = "{}/{}".format(rid, lid)
            if lane_type in ("sidewalk", "walkway"):
                inv["sidewalks"].add(lane_key)
            elif lane_type == "pedestrian":
                inv["pedestrian_lanes"].add(lane_key)
            for rm in lane.iter("roadMark"):
                inv["road_markings"].add("{}/{}/{}".format(
                    rid, lid, _el_attr(rm, "type") or _el_attr(rm, "width")))
            acc = lane.find("access")
            if acc is not None and _el_attr(acc, "restriction") == "no":
                inv["lane_change_permissions"].add(lane_key)
            if lane.find("link") is not None and (lane.find("link").find("predecessor") is not None
                                                  or lane.find("link").find("successor") is not None):
                inv["turn_lane_semantics"].add(lane_key)
            if lane_type in ("shoulder", "parking"):
                inv["lane_change_permissions"].add(lane_key)

        for lane_sec in road.iter("laneSection"):
            if lane_sec is None:
                continue
            for lane in lane_sec.iter("lane"):
                for surface in lane.iter("surface"):
                    for mat in surface.iter("material"):
                        inv["semantic_material_classes"].add(
                            "{}/{}/{}".format(rid, _el_attr(lane, "id"),
                                              _el_attr(mat, "name") or _el_attr(mat, "s")))

    return inv


def inventory_counts(inv: Dict[str, Set[str]]) -> Dict[str, int]:
    return {c: len(s) for c, s in inv.items()}


def compare_inventories(
    left: Dict[str, Set[str]],
    right: Dict[str, Set[str]],
    categories: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Compare two semantic inventories.

    Returns per-category missing (in left not right) and unexpected
    (in right not left) exact ID sets.
    """
    cats = list(categories) if categories else CATEGORIES
    rows = {}
    n_diff = 0
    for cat in cats:
        a = left.get(cat, set())
        b = right.get(cat, set())
        missing = sorted(a - b)
        unexpected = sorted(b - a)
        rows[cat] = {
            "left_count": len(a),
            "right_count": len(b),
            "missing_ids": missing,
            "unexpected_ids": unexpected,
            "missing_count": len(missing),
            "unexpected_count": len(unexpected),
            "equivalent": len(missing) == 0 and len(unexpected) == 0,
        }
        n_diff += len(missing) + len(unexpected)
    return {"total_difference_ids": n_diff, "categories": rows}


def semantic_equivalence_verdict(
    cmp: Dict[str, Any],
    decisive: Optional[Iterable[str]] = None,
) -> str:
    """SEMANTIC_EQUIVALENCE_PASS / PARTIAL / FAIL.

    PARTIAL is only allowed for non-decisive categories (e.g. runtime-only
    bindings not yet measurable).  Any difference in a decisive category fails.
    """
    decisive = set(decisive) if decisive is not None else PERCEPTION_DECISIVE
    rows = cmp["categories"]
    decisive_diffs = [c for c in decisive if not rows.get(c, {}).get("equivalent", True)]
    if decisive_diffs:
        return "SEMANTIC_EQUIVALENCE_FAIL"
    if cmp["total_difference_ids"] > 0:
        return "SEMANTIC_EQUIVALENCE_PARTIAL"
    return "SEMANTIC_EQUIVALENCE_PASS"


def compare_artifacts_pairs(
    reference: Dict[str, Set[str]],
    others: Dict[str, Dict[str, Set[str]]],
    categories: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Compare one reference artifact against many, verbatim ID sets."""
    out: Dict[str, Any] = {}
    for name, inv in others.items():
        cmp = compare_inventories(reference, inv, categories)
        out[name] = {
            "verdict": semantic_equivalence_verdict(cmp),
            "comparison": cmp,
        }
    return out


def load_inventory_from_json(payload: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Load an inventory persisted by `inventory_to_json`."""
    return {c: set(payload.get(c, [])) for c in CATEGORIES}


def inventory_to_json(inv: Dict[str, Set[str]]) -> Dict[str, List[str]]:
    return {c: sorted(s) for c, s in inv.items()}
