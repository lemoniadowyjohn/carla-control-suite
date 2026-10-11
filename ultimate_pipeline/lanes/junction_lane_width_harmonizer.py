"""GAP-026 generator-stage repair: junction lane-width harmonization.

Earliest proven bad stage: Stage 7 lane-width policy boundary.  Non-junction
(incoming) roads receive type-dependent widths (3.0/3.25/3.5/3.75 via
``lane_width_policy`` + OSM metadata) while junction connector roads
(``junction != -1``) unconditionally receive a single 3.5 m driving lane via
``LaneGenerator.ensure_lanes``.  Inner-to-inner laneLinks then carry a pure
lateral discontinuity of ``|w_inc - w_con| / 2`` (0.25 m for the dominant
3.0-vs-3.5 tier), with reference geometry already coincident.

This module runs at the source stage (Stage 7, after ``LaneWidthClamp`` and
before ``save_xodr``).  It mutates only ``<width @a>`` of connector driving
lanes that participate in a junction ``laneLink``, inheriting the matched
incoming lane's width.  It never touches planView geometry, contactPoint,
from/to mapping, thresholds, or the final XODR cosmetically.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(str(raw).strip())
    except Exception:
        return default
    return value


def harmonize_junction_lane_widths(root: ET.Element) -> Dict[str, Any]:
    """Inherit connector lane widths from matched incoming lanes.

    Returns a report dict with harmonized/residual counts.  Fail-closed on
    malformed input (missing roads/sections are skipped and counted, never
    guessed).
    """
    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}
    harmonized = 0
    checked_links = 0
    skipped_missing = 0
    residuals_wide = 0

    for junction in root.findall("junction"):
        for connection in junction.findall("connection"):
            incoming = roads.get(str(connection.get("incomingRoad")))
            connecting = roads.get(str(connection.get("connectingRoad")))
            if incoming is None or connecting is None:
                continue
            at_start = connection.get("contactPoint", "start") != "end"

            def edge_section(road: ET.Element, start: bool) -> ET.Element | None:
                sections = sorted(
                    road.findall("./lanes/laneSection"),
                    key=lambda s: _safe_float(s.get("s"), 0.0),
                )
                if not sections:
                    return None
                return sections[0] if start else sections[-1]

            inc_sec = edge_section(incoming, False)
            con_sec = edge_section(connecting, at_start)
            if inc_sec is None or con_sec is None:
                continue

            # Index incoming driving-lane widths by lane id at the interface.
            inc_widths: Dict[str, float] = {}
            for side_name in ("left", "right"):
                side = inc_sec.find(side_name)
                if side is None:
                    continue
                for lane in side.findall("lane"):
                    if lane.get("type", "driving") != "driving":
                        continue
                    width = lane.find("./width")
                    if width is None:
                        continue
                    try:
                        w = float(width.get("a"))
                    except (TypeError, ValueError):
                        continue
                    if w > 0:
                        inc_widths[str(lane.get("id"))] = w

            for lane_link in connection.findall("laneLink"):
                checked_links += 1
                from_id = str(lane_link.get("from"))
                to_id = str(lane_link.get("to"))
                src_w = inc_widths.get(from_id)
                if src_w is None:
                    skipped_missing += 1
                    continue
                # Locate the connector lane element at the contact section.
                target_lane = None
                try:
                    lane_int = int(to_id)
                except ValueError:
                    skipped_missing += 1
                    continue
                side = con_sec.find("left" if lane_int > 0 else "right")
                if side is None:
                    skipped_missing += 1
                    continue
                for lane in side.findall("lane"):
                    if str(lane.get("id")) == to_id and lane.get("type", "driving") == "driving":
                        target_lane = lane
                        break
                if target_lane is None:
                    skipped_missing += 1
                    continue
                width = target_lane.find("./width")
                if width is None:
                    skipped_missing += 1
                    continue
                try:
                    cur = float(width.get("a"))
                except (TypeError, ValueError):
                    skipped_missing += 1
                    continue
                if abs(cur - src_w) > 1e-9:
                    width.set("a", f"{src_w:.3f}")
                    harmonized += 1
                if abs(src_w - cur) > 1.0:
                    residuals_wide += 1

    return {
        "checked_lane_links": checked_links,
        "harmonized_widths": harmonized,
        "skipped_missing": skipped_missing,
        "residuals_wide": residuals_wide,
    }
