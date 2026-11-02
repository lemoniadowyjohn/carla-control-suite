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

Junction-type links are exempt from both checks here: they legitimately
carry no contactPoint on the road-level predecessor/successor element
(routing is resolved via the junction's own <connection> contactPoint and
laneLinks, a separate, already-covered concern). A pair where A points at
B but B's reciprocal slot routes through a junction (elementType !=
"road") is also exempt -- that is a legitimate junction-mediated
connection, not a missing direct road-to-road link.

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
                "dangling_target_skipped": int,
            },
            "contactpoint_invalid_examples": [...],  # up to max_examples
            "asymmetric_examples": [...],             # up to max_examples
        }
    """
    _tree, root = _load_tree_and_root(xodr_or_root)
    roads: Dict[str, ET.Element] = {
        r.get("id"): r for r in root.findall("./road") if r.get("id")
    }

    contactpoint_invalid: List[Dict[str, Any]] = []
    asymmetric: List[Dict[str, Any]] = []
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
                # Junction-mediated pair: B's reciprocal link routes
                # through a junction, not directly back to A. Legitimate.
                junction_mediated_exempt += 1
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

    violations = len(contactpoint_invalid) + len(asymmetric)
    return {
        "ok": violations == 0,
        "totals": {
            "roads_checked": len(roads),
            "road_road_links_checked": road_road_links_checked,
            "contactpoint_invalid_count": len(contactpoint_invalid),
            "asymmetric_count": len(asymmetric),
            "violations": violations,
            "junction_mediated_exempt": junction_mediated_exempt,
            "dangling_target_skipped": dangling_target_skipped,
        },
        "contactpoint_invalid_examples": contactpoint_invalid[:max_examples],
        "asymmetric_examples": asymmetric[:max_examples],
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
