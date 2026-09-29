"""Run a small analytical bias matrix against LaneLinkBuilder (O11)."""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder


def _road(root: ET.Element, rid: str, x: float, width: float = 3.5, offset: float = 0.0, junction: str = "-1") -> None:
    r = ET.SubElement(root, "road", {"id": rid, "junction": junction, "length": "10"})
    pv = ET.SubElement(r, "planView")
    g0 = ET.SubElement(pv, "geometry", {"s": "0", "x": str(x), "y": "0", "hdg": "0", "length": "10"})
    ET.SubElement(g0, "line")
    g1 = ET.SubElement(pv, "geometry", {"s": "10", "x": str(x + 10), "y": "0", "hdg": "0", "length": "0"})
    ET.SubElement(g1, "line")
    lanes = ET.SubElement(r, "lanes")
    ET.SubElement(lanes, "laneOffset", {"s": "0", "a": str(offset), "b": "0", "c": "0", "d": "0"})
    sec = ET.SubElement(lanes, "laneSection", {"s": "0"})
    right = ET.SubElement(sec, "right")
    ET.SubElement(right, "lane", {"id": "-1", "type": "driving"})
    ET.SubElement(right[-1], "width", {"sOffset": "0", "a": str(width), "b": "0", "c": "0", "d": "0"})


def _case(width_a: float, width_b: float, offset_b: float = 0.0, contact: str = "start", primitive: str = "line") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    _road(root, "1", 0.0, width_a)
    _road(root, "2", 10.0, width_b, offset_b, junction="2")
    j = ET.SubElement(root, "junction", {"id": "2"})
    c = ET.SubElement(j, "connection", {"id": "0", "incomingRoad": "1", "connectingRoad": "2", "contactPoint": contact})
    ET.SubElement(c, "laneLink", {"from": "-1", "to": "-1"})
    return root


def run_matrix() -> dict[str, Any]:
    cases = [
        ("equal_width", _case(3.5, 3.5), 0.0),
        ("unequal_width", _case(3.0, 3.5), 0.0),
        ("lane_offset", _case(3.5, 3.5, offset_b=0.25), 1),
        ("contact_start", _case(3.5, 3.5, contact="start"), 0.0),
        ("contact_end", _case(3.5, 3.5, contact="end"), 1),
        ("line_endpoint", _case(3.5, 3.5), 0.0),
    ]
    rows = []
    for name, root, expected in cases:
        result = LaneLinkBuilder.sanitize_junction_lane_links(root, label=name)
        actual_failed = result["summary_metrics"]["failed"]
        rows.append({"case": name, "expected_failed": expected, "production_failed": actual_failed, "analytically_validated": expected is not None, "status": "PASS" if expected is not None and ((expected == 0 and actual_failed == 0) or (expected > 0 and actual_failed > 0)) else "INCONCLUSIVE"})
    return {"schema": "gap026_checker_bias_matrix/v1", "status": "INCONCLUSIVE" if any(r["status"] == "INCONCLUSIVE" for r in rows) else "PASS", "production_checker": "ultimate_pipeline.lanes.lanelink_builder.LaneLinkBuilder.sanitize_junction_lane_links", "rows": rows, "limitations": ["Synthetic cases cover analytical straight-line semantics; this matrix does not authorize checker implementation changes."]}


if __name__ == "__main__":
    print(json.dumps(run_matrix(), indent=2, sort_keys=True))
