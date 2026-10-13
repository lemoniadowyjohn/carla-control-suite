#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""CARLA-critical lane connectivity validation.

CARLA can crash/ASSERT if a *driving* lane has no successor. This module:
- detects broken driving lanes (missing <link> or <successor>)
- writes a JSON report (evidence for thesis)
- optionally mitigates by downgrading only the broken driving lanes to type=none
  (opt-in; avoids deleting roads)

A driving lane on a road whose successor is a junction is NOT broken when
the lane is routed through that junction by at least one VALID laneLink
(``connection/@incomingRoad`` matches, ``laneLink/@from`` matches, connecting
road exists, target lane exists at the contact section). Rationale
(GAP-048 closure): cross-junction lane connectivity is authoritatively
defined by junction connections + laneLinks -- the repository lane graph
(``map_acceptance.component_reachability_summary``) builds cross-junction
edges exclusively from laneLinks, and the CARLA compat gate
(``check_carla_opendrive_compat``) lists junction laneLinks (not lane-level
successors) as the routing authority. A lane-level ``<successor id>`` on a
terminal junction-boundary lane carries only a lane id (no road reference);
it cannot express road choice and is treated as a road-end marker by the
reachability analysis. Flagging explicitly-routed lanes while exempting
unconnected dead ends would invert strictness, so junction-routed lanes are
excluded from the broken set (independent of ``allow_dead_ends``).

Input: path to .xodr or XML root element.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from ultimate_pipeline.artifacts.map_event_record import append_event, build_record

def _load_tree_and_root(xodr_or_root: Union[str, os.PathLike, ET.Element]) -> Tuple[ET.ElementTree, ET.Element]:
    if isinstance(xodr_or_root, ET.Element):
        # Create a dummy tree wrapper so callers can keep a uniform API.
        tree = ET.ElementTree(xodr_or_root)
        return tree, xodr_or_root

    if not isinstance(xodr_or_root, (str, os.PathLike)):
        raise TypeError(f"Expected xodr path or XML Element, got {type(xodr_or_root)}")

    tree = ET.parse(str(xodr_or_root))
    return tree, tree.getroot()


def _contact_section_driving_ids(road: ET.Element, at_start: bool) -> set:
    """Driving lane ids at a road boundary section (contact-point aware)."""
    sections = list(road.findall("./lanes/laneSection"))

    def _s(sec: ET.Element) -> float:
        try:
            return float(sec.get("s", "0") or 0.0)
        except Exception:
            return 0.0

    if not sections:
        return set()
    section = min(sections, key=_s) if at_start else max(sections, key=_s)
    out: set = set()
    for side in ("left", "right"):
        side_elem = section.find(side)
        if side_elem is None:
            continue
        for lane in side_elem.findall("lane"):
            if lane.get("type") == "driving":
                out.add(lane.get("id"))
    return out


def _lane_has_valid_junction_lanelink(
    roads_by_id: Dict[str, ET.Element],
    junctions_by_id: Dict[str, ET.Element],
    road_id: str,
    lane_id_str: str,
) -> bool:
    """True iff the lane is explicitly routed through its successor junction.

    Requires: parent road successor elementType == junction, and at least one
    laneLink with from == lane id on a connection with
    incomingRoad == road_id whose contactPoint is valid, whose connecting
    road exists, and whose to-lane exists at that road's contact section.
    Mirrors the GAP-048 population classifier funnel (same boundary
    semantics as the GAP-026 checker); does NOT consider road identity
    beyond existence -- road choice stays with the laneLinks themselves.
    """
    road = roads_by_id.get(road_id)
    if road is None:
        return False
    link = road.find("link")
    succ = link.find("successor") if link is not None else None
    if succ is None or succ.get("elementType") != "junction":
        return False
    junction = junctions_by_id.get(succ.get("elementId"))
    if junction is None:
        return False
    for conn in junction.findall("connection"):
        if conn.get("incomingRoad") != road_id:
            continue
        contact = conn.get("contactPoint", "start")
        if contact not in ("start", "end"):
            continue
        connecting = conn.get("connectingRoad")
        if not connecting:
            continue
        target_road = roads_by_id.get(connecting)
        if target_road is None:
            continue
        at_start = contact != "end"
        valid_ids = _contact_section_driving_ids(target_road, at_start)
        for lane_link in conn.findall("laneLink"):
            if lane_link.get("from") != lane_id_str:
                continue
            if lane_link.get("to") in valid_ids:
                return True
    return False


def find_broken_lanes_detailed(
    xodr_or_root: Union[str, os.PathLike, ET.Element],
    *,
    allow_dead_ends: bool = True,
) -> List[Dict[str, Any]]:
    """Return structured records for driving lanes that violate successor requirements."""
    _tree, root = _load_tree_and_root(xodr_or_root)
    broken: List[Dict[str, Any]] = []
    roads_by_id = {r.get("id"): r for r in root.findall("./road") if r.get("id")}
    junctions_by_id = {j.get("id"): j for j in root.findall("./junction")}

    for road in root.findall("./road"):
        road_id = road.get("id", "?")
        junction = road.get("junction", "?")

        # Road-level successor drives the lane-level expectation.
        # If a road has no successor and dead-ends are allowed, we do not require
        # lane-level <link>/<successor> elements (common at map boundaries).
        road_successor = road.find("./link/successor")

        # Terminal-section membership per lane (document order preserved).
        sections = list(road.findall("./lanes/laneSection"))

        def _s(sec: ET.Element) -> float:
            try:
                return float(sec.get("s", "0") or 0.0)
            except Exception:
                return 0.0

        terminal_sec = None
        if sections:
            max_s = max(_s(sec) for sec in sections)
            for sec in sections:
                if _s(sec) == max_s:
                    terminal_sec = sec

        for lane_section in sections:
            is_terminal = terminal_sec is not None and lane_section is terminal_sec
            for lane in lane_section.findall(".//lane[@type='driving']"):
                lane_id = lane.get("id", "?")
                link = lane.find("link")
                if link is None:
                    if allow_dead_ends and junction == "-1" and road_successor is None:
                        continue
                    if is_terminal and _lane_has_valid_junction_lanelink(
                        roads_by_id, junctions_by_id, road_id, lane_id
                    ):
                        # Junction-routed (GAP-048 closure): explicit laneLink
                        # connectivity exists; no lane-level successor required.
                        continue
                    broken.append({
                        "road_id": road_id,
                        "lane_id": lane_id,
                        "junction": junction,
                        "reason": "missing_link",
                    })
                    continue

                successor = link.find("successor")
                if successor is None:
                    # Allow (some) dead ends: keep behaviour compatible with existing code.
                    # NOTE: this is intentionally conservative; dead-end policy is thesis-dependent.
                    if allow_dead_ends and junction == "-1" and road_successor is None:
                        # Non-junction roads without successors are likely boundary dead-ends.
                        continue
                    if is_terminal and _lane_has_valid_junction_lanelink(
                        roads_by_id, junctions_by_id, road_id, lane_id
                    ):
                        # Junction-routed (GAP-048 closure): see above.
                        continue

                    broken.append({
                        "road_id": road_id,
                        "lane_id": lane_id,
                        "junction": junction,
                        "reason": "missing_successor",
                    })

    return broken


def find_broken_lanes(
    xodr_or_root: Union[str, os.PathLike, ET.Element],
    *,
    allow_dead_ends: bool = True,
) -> List[str]:
    """Backwards compatible: return human-readable messages."""
    broken = find_broken_lanes_detailed(xodr_or_root, allow_dead_ends=allow_dead_ends)
    msgs: List[str] = []
    for b in broken:
        if b["reason"] == "missing_link":
            msgs.append(f"Road {b['road_id']} lane {b['lane_id']}: missing <link>")
        else:
            msgs.append(f"Road {b['road_id']} lane {b['lane_id']}: missing <successor>")
    return msgs


def write_lane_connectivity_report(
    *,
    xodr_path: Union[str, os.PathLike],
    out_json: Union[str, os.PathLike],
    allow_dead_ends: bool = True,
) -> Dict[str, Any]:
    """Write a JSON report describing broken driving lanes."""
    xodr_path = Path(xodr_path)
    out_json = Path(out_json)
    broken = find_broken_lanes_detailed(xodr_path, allow_dead_ends=allow_dead_ends)

    report: Dict[str, Any] = {
        "xodr": str(xodr_path),
        "allow_dead_ends": allow_dead_ends,
        "broken_count": len(broken),
        "broken": broken,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def downgrade_broken_driving_lanes_to_none(
    *,
    xodr_in: Union[str, os.PathLike],
    xodr_out: Union[str, os.PathLike],
    allow_dead_ends: bool = True,
    out_json: Union[str, os.PathLike, None] = None,
) -> Dict[str, Any]:
    """Create a CARLA-loadable variant by downgrading broken driving lanes.

    This does NOT delete roads. It only changes specific lane elements:
    - lane[@type='driving'] -> lane[@type='none']
    - removes the lane's <link> element (prevents partial/broken link usage)

    Returns a report dict. If out_json is provided, writes it.
    """
    xodr_in = Path(xodr_in)
    xodr_out = Path(xodr_out)

    tree, root = _load_tree_and_root(xodr_in)
    broken = find_broken_lanes_detailed(root, allow_dead_ends=allow_dead_ends)

    # Fast lookup set for (road_id, lane_id)
    broken_keys = {(b["road_id"], str(b["lane_id"])) for b in broken}
    downgraded: List[Dict[str, Any]] = []

    event_payloads: List[Dict[str, Any]] = []

    for road in root.findall("./road"):
        road_id = road.get("id", "?")
        road_len = None
        try:
            road_len = float(road.get("length", "0.0"))
        except Exception:
            road_len = None
        lanes_elem = road.find("lanes")
        lane_sections = list(lanes_elem.findall("laneSection")) if lanes_elem is not None else []
        lane_sections.sort(key=lambda e: float(e.get("s", "0") or 0.0))
        s_vals = [float(ls.get("s", "0") or 0.0) for ls in lane_sections]

        for ls_idx, ls in enumerate(lane_sections):
            s_from = s_vals[ls_idx] if ls_idx < len(s_vals) else None
            s_to = None
            if s_from is not None:
                if ls_idx + 1 < len(s_vals):
                    s_to = s_vals[ls_idx + 1]
                elif road_len is not None:
                    s_to = road_len

            for lane in ls.findall(".//lane[@type='driving']"):
                lane_id = lane.get("id", "?")
                if (road_id, str(lane_id)) not in broken_keys:
                    continue

                # broken_keys is (road_id, lane_id) only -- not laneSection-
                # specific. Roads with multiple laneSections commonly reuse
                # the same lane id across sections (e.g. a lane-count/width
                # transition), so this key alone cannot tell apart "this
                # exact lane is broken" from "a DIFFERENT laneSection's lane
                # with the same id is broken". Re-derive this specific
                # lane's own broken/not-broken state (same test
                # find_broken_lanes_detailed uses) before mutating it.
                link = lane.find("link")
                if link is not None and link.find("successor") is not None:
                    continue

                lane.set("type", "none")
                if link is not None:
                    lane.remove(link)

                downgraded.append({"road_id": road_id, "lane_id": lane_id})

                removed_len = None
                removed_pct = None
                if s_from is not None and s_to is not None:
                    removed_len = float(max(0.0, s_to - s_from))
                    if road_len and road_len > 0:
                        removed_pct = float(removed_len / road_len)
                event_payloads.append(
                    {
                        "road_id": str(road_id),
                        "lane_section_id": str(ls_idx),
                        "lane_id": str(lane_id),
                        "junction_id": road.get("junction"),
                        "s_from": s_from,
                        "s_to": s_to,
                        "removed_length_m": removed_len,
                        "removed_length_pct": removed_pct,
                    }
                )

    xodr_out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(xodr_out), encoding="utf-8", xml_declaration=True)
    out_dir = str(xodr_out.parent)
    for payload in event_payloads:
        record = build_record(
            out_dir=out_dir,
            final_xodr_path=str(xodr_out),
            stage_name="lane_connectivity",
            gate_name="downgrade_broken_driving_lanes_to_none",
            event_type="mask",
            road_id=payload["road_id"],
            lane_section_id=payload["lane_section_id"],
            lane_id=payload["lane_id"],
            junction_id=payload["junction_id"],
            s_from=payload["s_from"],
            s_to=payload["s_to"],
            removed_length_m=payload["removed_length_m"],
            removed_length_pct=payload["removed_length_pct"],
        )
        append_event(out_dir, record)

    report: Dict[str, Any] = {
        "xodr_in": str(xodr_in),
        "xodr_out": str(xodr_out),
        "allow_dead_ends": allow_dead_ends,
        "broken_count": len(broken),
        "downgraded_count": len(downgraded),
        "downgraded": downgraded,
    }

    if out_json is not None:
        out_path = Path(out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return report


def autofix_missing_lane_successors(
    xodr_path: Union[str, os.PathLike],
    *,
    allow_dead_ends: bool = True,
    output_path: Union[str, os.PathLike, None] = None,
) -> Dict[str, Any]:
    """Attempt to repair missing lane successors by inferring from road links.

    Strategy:
    - For each driving lane missing <successor>:
      - If the parent road has a successor link, create a lane successor
        pointing to the same lane id on the successor road.
      - If the road is a dead end (no successor) and allow_dead_ends=True, skip.
      - If no safe successor can be inferred, leave it broken and report.

    Returns a report dict with: broken_before, fixed, still_broken, output_path.
    """
    import time

    xodr_path = Path(xodr_path)
    if output_path is None:
        output_path = xodr_path.parent / (xodr_path.stem + "_lane_successor_fixed.xodr")
    output_path = Path(output_path)

    tree, root = _load_tree_and_root(xodr_path)

    # Find broken lanes before fix
    broken_before = find_broken_lanes_detailed(root, allow_dead_ends=allow_dead_ends)
    broken_before_set = {(b["road_id"], str(b["lane_id"])) for b in broken_before}

    fixed_lanes: List[Dict[str, Any]] = []
    still_broken: List[Dict[str, Any]] = []

    for road in root.findall("./road"):
        road_id = road.get("id", "?")
        junction = road.get("junction", "-1")

        # Get road-level successor link
        road_link = road.find("link")
        road_successor = road_link.find("successor") if road_link is not None else None
        successor_road_id = road_successor.get("elementId") if road_successor is not None else None
        successor_contact = road_successor.get("contactPoint", "start") if road_successor is not None else None

        # Iterate over all laneSections
        lane_sections = road.findall("./lanes/laneSection")
        for ls_idx, lane_section in enumerate(lane_sections):
            is_last_section = (ls_idx == len(lane_sections) - 1)

            for lane in lane_section.findall(".//lane[@type='driving']"):
                lane_id = lane.get("id", "?")

                # Skip if not in broken set
                if (road_id, str(lane_id)) not in broken_before_set:
                    continue

                link = lane.find("link")
                if link is None:
                    # Create <link> element
                    link = ET.SubElement(lane, "link")

                successor = link.find("successor")
                if successor is not None:
                    # Already has successor (shouldn't be in broken set, but skip)
                    continue

                # Determine if we can infer a successor
                can_fix = False
                fix_reason = ""

                if is_last_section and successor_road_id is not None:
                    # Last laneSection and road has successor -> create lane successor
                    successor_elem = ET.SubElement(link, "successor")
                    successor_elem.set("id", str(lane_id))  # Same lane id on successor road
                    can_fix = True
                    fix_reason = f"inferred from road successor (road {successor_road_id})"
                elif not is_last_section:
                    # Not last laneSection -> successor is same lane id in next section
                    successor_elem = ET.SubElement(link, "successor")
                    successor_elem.set("id", str(lane_id))
                    can_fix = True
                    fix_reason = "inferred from next laneSection"
                elif allow_dead_ends and junction == "-1" and successor_road_id is None:
                    # Dead end road, allowed -> skip (not actually broken per policy)
                    continue
                else:
                    # Cannot infer
                    fix_reason = "no road successor and not a dead end"

                if can_fix:
                    fixed_lanes.append({
                        "road_id": road_id,
                        "lane_id": lane_id,
                        "laneSection_index": ls_idx,
                        "fix_reason": fix_reason,
                    })
                else:
                    still_broken.append({
                        "road_id": road_id,
                        "lane_id": lane_id,
                        "laneSection_index": ls_idx,
                        "reason": fix_reason,
                    })

    # Write fixed XODR
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)

    report: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "strategy": "infer_from_road_links",
        "input_xodr": str(xodr_path),
        "output_xodr": str(output_path),
        "allow_dead_ends": allow_dead_ends,
        "broken_before_count": len(broken_before),
        "broken_before": broken_before,
        "fixed_count": len(fixed_lanes),
        "fixed": fixed_lanes,
        "still_broken_count": len(still_broken),
        "still_broken": still_broken,
    }

    return report


def assert_all_lanes_have_successors(
    xodr_or_root: Union[str, os.PathLike, ET.Element],
    *,
    allow_dead_ends: bool = True,
) -> None:
    """HARD FAIL if any driving lane lacks a successor."""
    errors = find_broken_lanes(xodr_or_root, allow_dead_ends=allow_dead_ends)
    if not errors:
        return

    preview = "\n".join(errors[:20])
    raise RuntimeError(
        f"""
❌ CARLA-FATAL: lane connectivity invariant violated

CARLA requires every driving lane to have a successor.
The following lanes are invalid:

{preview}

Total broken lanes: {len(errors)}

Fix lane links BEFORE CARLA load.
"""
    )
