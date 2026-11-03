#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Road-to-road <link> contactPoint + reciprocity validation (L2 review).

Validation-only (no mutation). Checks, for every ROAD-type road-level
<link><predecessor/successor>:

(a) contactPoint is present and one of {"start", "end"}. A missing or
    invalid contactPoint on a road->road link means the topology does not
    unambiguously name which boundary of the linked road is touched; it is
    reported as a `contactpoint_invalid` violation, never assumed.

(b) reciprocity: if road A's predecessor/successor names road B at B's
    start/end (ASAM OpenDRIVE 10.3: contactPoint names the boundary of the
    LINKED element), then B's own link element defined at that boundary
    (B's predecessor if contact=="start", B's successor if contact=="end")
    must point back at A (elementType="road", elementId==A) with the
    contactPoint naming A's own touched boundary ("start" if A's link slot
    is `predecessor`, "end" if it is `successor`). Reported as an
    `asymmetric` violation when it doesn't.

Junction-type links are exempt from the contactPoint-presence check: they
legitimately carry no contactPoint on the road-level predecessor/successor
element (routing is resolved via the junction's own <connection>
contactPoint and laneLinks, a separate, already-covered concern).

A pair where A points at B but B's reciprocal slot routes through a
junction (elementType != "road") is exempt from the reciprocity check
ONLY if the referenced <junction> element actually exists AND has a
<connection> that links A and B (incomingRoad/connectingRoad naming A and
B, in either orientation -- ASAM OpenDRIVE: a junction's connecting roads
carry a predecessor/successor naming their incoming road, and incoming
roads carry a road-level link naming the junction). A junction id that
does not exist, or exists but has no <connection> tying A and B together,
is NOT a legitimate exemption -- it is reported as a distinct
`junction_reference_unbacked` violation (L2 review, 2026-11-02: the prior
unconditional "elementType != road => exempt" rule let an unrelated or
dangling junction id silently mask a missing direct link).

Input: path to .xodr or an already-parsed XML root Element.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple, Union

# contactPoint on A's link -> which of B's own link slots is the
# reciprocal one (the slot defined at the boundary of B that is touched).
_CONTACT_TO_RECIPROCAL_SLOT = {"start": "predecessor", "end": "successor"}
# A's own link slot -> the contactPoint B's reciprocal link must carry
# (naming the boundary of A that is touched).
_SLOT_TO_EXPECTED_RECIPROCAL_CONTACT = {"predecessor": "start", "successor": "end"}


def _build_junction_connection_pairs(
    root: ET.Element,
) -> Dict[str, List[Tuple[str, str]]]:
    """Map junction id -> list of (incomingRoad, connectingRoad) pairs."""
    junctions: Dict[str, List[Tuple[str, str]]] = {}
    for junction in root.findall("./junction"):
        junction_id = junction.get("id")
        if not junction_id:
            continue
        pairs: List[Tuple[str, str]] = []
        for conn in junction.findall("connection"):
            incoming = conn.get("incomingRoad")
            connecting = conn.get("connectingRoad")
            if incoming and connecting:
                pairs.append((incoming, connecting))
        junctions[junction_id] = pairs
    return junctions


def _boundary_xy(road: ET.Element, at_end: bool) -> Union[Tuple[float, float], None]:
    from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s

    geometries = road.findall("./planView/geometry")
    if not geometries:
        return None
    try:
        geometries.sort(key=lambda g: float(g.get("s", "0") or 0.0))
        pose = endpoint(geometries[-1]) if at_end else pose_at_s(geometries[0], 0.0)
        return pose.x, pose.y
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _carriageway_width(road: ET.Element, at_end: bool) -> float:
    """Sum of lane widths of the first/last laneSection at the road boundary."""
    sections = road.findall("./lanes/laneSection")
    if not sections:
        return 0.0
    section = sections[-1] if at_end else sections[0]
    try:
        length = float(road.get("length", "0") or 0.0)
        ds = (length - float(section.get("s", "0") or 0.0)) if at_end else 0.0
    except (TypeError, ValueError):
        return 0.0
    total = 0.0
    for lane in section.findall("./left/lane") + section.findall("./right/lane"):
        widths = lane.findall("width")
        if not widths:
            continue
        w = widths[-1] if at_end else widths[0]
        try:
            a, b, c, d = (float(w.get(k, "0") or 0.0) for k in "abcd")
            t = ds - float(w.get("sOffset", "0") or 0.0) if at_end else 0.0
        except (TypeError, ValueError):
            continue
        total += max(0.0, a + b * t + c * t * t + d * t ** 3)
    return total


def _exit_geometry_gap(
    a: ET.Element, b: ET.Element, slot_a: str, contact_b: str
) -> Union[Tuple[float, float], None]:
    """(reference-line gap, combined carriageway width) at the touching ends.

    Reference lines of a connecting road and its exit road need not coincide
    (a one-way road's reference line sits at its lane edge, so on the real
    map they are typically ~6.5 m apart); the carriageways must still
    overlap, i.e. gap <= combined width.
    """
    a_xy = _boundary_xy(a, at_end=(slot_a == "successor"))
    b_xy = _boundary_xy(b, at_end=(contact_b == "end"))
    if a_xy is None or b_xy is None:
        return None
    gap = ((a_xy[0] - b_xy[0]) ** 2 + (a_xy[1] - b_xy[1]) ** 2) ** 0.5
    width = _carriageway_width(a, slot_a == "successor") + _carriageway_width(b, contact_b == "end")
    return gap, width


def _junction_connects_roads(
    junctions: Dict[str, List[Tuple[str, str]]],
    junction_id: Union[str, None],
    road_a: str,
    road_b: str,
    *,
    roads: Union[Dict[str, ET.Element], None] = None,
) -> Union[str, None]:
    """How junction_id backs the A->B link: "connection", "exit" or None.

    "connection": a <connection> names A and B (in either order).
    "exit": A is the junction's own connecting road (listed as its
    connectingRoad AND road@junction == junction_id) leaving it into exit
    road B. A <connection> lists only incomingRoad/connectingRoad, so a
    one-way exit road never appears in one. Structure alone cannot tell a
    real exit from an unrelated road naming the same junction; the caller
    checks the exit geometry separately (_exit_geometry_gap).
    """
    if not junction_id:
        return None
    pairs = junctions.get(junction_id)
    if pairs is None:
        return None
    target = {road_a, road_b}
    for incoming, connecting in pairs:
        if {incoming, connecting} == target:
            return "connection"
    if not any(connecting == road_a for _incoming, connecting in pairs):
        return None
    a = roads.get(road_a) if roads is not None else None
    if a is None or str(a.get("junction", "-1")) != str(junction_id):
        return None
    return "exit"


def _load_tree_and_root(
    xodr_or_root: Union[str, os.PathLike, ET.Element]
) -> Tuple[ET.ElementTree, ET.Element]:
    if isinstance(xodr_or_root, ET.Element):
        tree = ET.ElementTree(xodr_or_root)
        return tree, xodr_or_root
    if not isinstance(xodr_or_root, (str, os.PathLike)):
        raise TypeError(f"Expected xodr path or XML Element, got {type(xodr_or_root)}")
    tree = ET.parse(str(xodr_or_root))
    return tree, tree.getroot()


def check_road_link_reciprocity(
    xodr_or_root: Union[str, os.PathLike, ET.Element],
    max_examples: int = 200,
) -> Dict[str, Any]:
    """Validate road->road link contactPoint presence + reciprocity.

    Returns a report dict:
        {
            "ok": bool,
            "totals": {
                "roads_checked": int,
                "road_road_links_checked": int,
                "contactpoint_invalid_count": int,
                "asymmetric_count": int,
                "violations": int,
                "junction_mediated_exempt": int,
                "junction_reference_unbacked_count": int,
                "dangling_target_skipped": int,
            },
            "contactpoint_invalid_examples": [...],  # up to max_examples
            "asymmetric_examples": [...],             # up to max_examples
            "junction_reference_unbacked_examples": [...],  # up to max_examples
        }
    """
    _tree, root = _load_tree_and_root(xodr_or_root)
    roads: Dict[str, ET.Element] = {
        r.get("id"): r for r in root.findall("./road") if r.get("id")
    }
    junctions = _build_junction_connection_pairs(root)

    contactpoint_invalid: List[Dict[str, Any]] = []
    asymmetric: List[Dict[str, Any]] = []
    junction_reference_unbacked: List[Dict[str, Any]] = []
    # Report-only: structurally backed junction exits whose carriageways do
    # not meet (or cannot be measured). Not counted in `violations`.
    junction_exit_geometry_gap: List[Dict[str, Any]] = []
    road_road_links_checked = 0
    junction_mediated_exempt = 0
    dangling_target_skipped = 0

    for road_id, road in roads.items():
        link = road.find("link")
        if link is None:
            continue
        for slot in ("predecessor", "successor"):
            elem = link.find(slot)
            if elem is None:
                continue
            element_type = elem.get("elementType")
            if element_type != "road":
                # Junction-type links legitimately have no contactPoint
                # requirement here; out of scope for this checker.
                continue
            target_id = elem.get("elementId")
            contact = elem.get("contactPoint")

            if contact not in ("start", "end"):
                contactpoint_invalid.append({
                    "road_id": road_id,
                    "slot": slot,
                    "target_id": target_id,
                    "contact_point": contact,
                })
                continue

            target_road = roads.get(target_id)
            if target_road is None:
                # Dangling target id is a different checker's concern
                # (check_lane_link_targets_exist / orphan repair).
                dangling_target_skipped += 1
                continue

            road_road_links_checked += 1
            target_link = target_road.find("link")
            reciprocal_slot_name = _CONTACT_TO_RECIPROCAL_SLOT[contact]
            reciprocal_elem = (
                target_link.find(reciprocal_slot_name) if target_link is not None else None
            )
            if reciprocal_elem is None:
                asymmetric.append({
                    "road_id": road_id,
                    "slot": slot,
                    "target_id": target_id,
                    "contact_point": contact,
                    "reason": (
                        f"target road {target_id!r} has no {reciprocal_slot_name} "
                        "link back to this road"
                    ),
                })
                continue

            reciprocal_element_type = reciprocal_elem.get("elementType")
            if reciprocal_element_type != "road":
                # B's reciprocal link routes through a junction instead of
                # directly back to A. Legitimate ONLY if that junction
                # exists and actually has a <connection> linking A and B;
                # otherwise this is an unbacked reference masquerading as
                # a junction-mediated connection.
                reciprocal_junction_id = reciprocal_elem.get("elementId")
                backing = _junction_connects_roads(
                    junctions, reciprocal_junction_id, road_id, target_id,
                    roads=roads,
                )
                if backing:
                    junction_mediated_exempt += 1
                    if backing == "exit":
                        measured = _exit_geometry_gap(road, target_road, slot, contact)
                        if measured is None or measured[0] > measured[1]:
                            junction_exit_geometry_gap.append({
                                "road_id": road_id,
                                "slot": slot,
                                "target_id": target_id,
                                "contact_point": contact,
                                "junction_id": reciprocal_junction_id,
                                "reference_line_gap_m": None if measured is None else round(measured[0], 3),
                                "carriageway_width_m": None if measured is None else round(measured[1], 3),
                            })
                else:
                    junction_reference_unbacked.append({
                        "road_id": road_id,
                        "slot": slot,
                        "target_id": target_id,
                        "contact_point": contact,
                        "reciprocal_slot": reciprocal_slot_name,
                        "junction_id": reciprocal_junction_id,
                        "reason": (
                            f"junction {reciprocal_junction_id!r} "
                            "referenced by target road "
                            f"{target_id!r}'s {reciprocal_slot_name} does "
                            "not exist or has no <connection> linking "
                            f"{road_id!r} and {target_id!r}"
                        ),
                    })
                continue

            reciprocal_target_id = reciprocal_elem.get("elementId")
            reciprocal_contact = reciprocal_elem.get("contactPoint")
            expected_reciprocal_contact = _SLOT_TO_EXPECTED_RECIPROCAL_CONTACT[slot]
            if (
                reciprocal_target_id != road_id
                or reciprocal_contact != expected_reciprocal_contact
            ):
                asymmetric.append({
                    "road_id": road_id,
                    "slot": slot,
                    "target_id": target_id,
                    "contact_point": contact,
                    "reciprocal_slot": reciprocal_slot_name,
                    "reciprocal_target_id": reciprocal_target_id,
                    "reciprocal_contact_point": reciprocal_contact,
                    "expected_reciprocal_contact_point": expected_reciprocal_contact,
                })

    violations = (
        len(contactpoint_invalid)
        + len(asymmetric)
        + len(junction_reference_unbacked)
    )
    return {
        "ok": violations == 0,
        "totals": {
            "roads_checked": len(roads),
            "road_road_links_checked": road_road_links_checked,
            "contactpoint_invalid_count": len(contactpoint_invalid),
            "asymmetric_count": len(asymmetric),
            "junction_reference_unbacked_count": len(junction_reference_unbacked),
            "violations": violations,
            "junction_mediated_exempt": junction_mediated_exempt,
            "dangling_target_skipped": dangling_target_skipped,
            "junction_exit_geometry_gap_count": len(junction_exit_geometry_gap),
        },
        "contactpoint_invalid_examples": contactpoint_invalid[:max_examples],
        "asymmetric_examples": asymmetric[:max_examples],
        "junction_reference_unbacked_examples": junction_reference_unbacked[:max_examples],
        "junction_exit_geometry_gap_examples": junction_exit_geometry_gap[:max_examples],
    }


# CLI for standalone/manual evidence collection
if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Validate road->road link contactPoint presence + reciprocity"
    )
    parser.add_argument("--xodr", required=True, help="Input XODR (read-only)")
    parser.add_argument("--report", help="JSON report path")
    args = parser.parse_args()

    result = check_road_link_reciprocity(args.xodr)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
    print(json.dumps(result["totals"], indent=2, sort_keys=True))
    sys.exit(0 if result["ok"] else 1)
