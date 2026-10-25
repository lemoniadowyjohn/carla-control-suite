#!/usr/bin/env python3
"""L1/L2: tests for the fixed orphan_road_repair.py.

Defect regression coverage (per adversarial review of f59212b3):
1. Heading is NOT double-converted to radians
2. Correct reciprocal link types and ASAM contactPoint semantics
   (contactPoint names the contact on the LINKED element)
3. _link_exists() works on a successor-only road (UnboundLocalError + wrong
   variable regression)
4. Existing predecessor/successor slots are never overwritten
5. Duplicate/overlapping same-direction roads are rejected (same-side pairs
   require opposite headings)
6. Default threshold is 5.0 m
7. strict mode raises on residual orphans even when some were repaired
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import xml.etree.ElementTree as ET
import math

from ultimate_pipeline.topology.orphan_road_repair import (
    repair_orphan_roads, _road_endpoints, _heading_at_end,
    _link_exists, _link_slot_occupied,
)


def _xml_road(road_id, x0, y0, hdg, length, with_link=None):
    road = ET.Element("road", {"id": road_id, "name": f"road_{road_id}", "junction": "-1"})
    planView = ET.SubElement(road, "planView")
    geom = ET.SubElement(planView, "geometry", {
        "s": "0.0", "x": str(x0), "y": str(y0), "hdg": str(hdg), "length": str(length)
    })
    ET.SubElement(geom, "line")
    lanes = ET.SubElement(road, "lanes")
    laneSec = ET.SubElement(lanes, "laneSection", {"s": "0.0"})
    right = ET.SubElement(laneSec, "right")
    ET.SubElement(right, "lane", {"id": "1", "type": "driving", "level": "false"})
    if with_link is not None:
        link = ET.SubElement(road, "link")
        for link_type, target_id, contact in with_link:
            elem = ET.SubElement(link, link_type)
            elem.set("elementType", "road")
            elem.set("elementId", target_id)
            elem.set("contactPoint", contact)
    return road


def _root(*roads, junction_incoming=None):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    if junction_incoming:
        junction = ET.SubElement(root, "junction", {"id": "j1"})
        ET.SubElement(junction, "connection", {
            "id": "0", "incomingRoad": junction_incoming, "connectingRoad": "9",
            "contactPoint": "start",
        })
    return root


def test_heading_not_double_converted():
    """XODR hdg is already in radians - no math.radians() conversion."""
    road = _xml_road("1", 0.0, 0.0, math.pi / 2, 100.0)
    ends = _road_endpoints(road)
    assert abs(ends[0][0] - 0.0) < 0.01 and abs(ends[0][1] - 0.0) < 0.01
    assert abs(ends[1][0] - 0.0) < 0.01 and abs(ends[1][1] - 100.0) < 0.01
    print("PASS: heading not double-converted")


def test_heading_at_end():
    road = _xml_road("1", 0.0, 0.0, 0.0, 100.0)
    assert abs(_heading_at_end(road) - 0.0) < 0.01
    road2 = _xml_road("2", 0.0, 0.0, math.pi, 100.0)
    assert abs(_heading_at_end(road2) - math.pi) < 0.01
    print("PASS: heading at end correct")


def test_repair_reciprocal_links_and_contactpoints():
    """Chain orphan end -> target start.

    ASAM 10.3: contactPoint names the contact on the LINKED element:
    - orphan successor (linked = target) touches target at its START
    - target predecessor (linked = orphan) touches orphan at its END
    Matches the repo convention in test_topology_validation.py
    (successor cp="start" + predecessor cp="end" == mutual OK).
    """
    orphan = _xml_road("A", 0.0, 0.0, 0.0, 100.0)          # start (0,0), end (100,0)
    target = _xml_road("B", 100.0, 0.0, 0.0, 100.0)        # start (100,0), end (200,0)
    root = _root(orphan, target, junction_incoming="B")

    report = repair_orphan_roads(root, max_snap_m=5.0)
    assert report["repaired_connections"] == 1, report
    assert report["residual_unconnected"] == 0, report

    # Orphan side
    orphan_link = orphan.find("link")
    succ = orphan_link.find("successor")
    pred = orphan_link.find("predecessor")
    assert succ is not None and pred is None
    assert succ.get("elementType") == "road"
    assert succ.get("elementId") == "B"
    assert succ.get("contactPoint") == "start", succ.attrib
    # Target side (reciprocal)
    target_link = target.find("link")
    t_succ = target_link.find("successor")
    t_pred = target_link.find("predecessor")
    assert t_pred is not None and t_succ is None
    assert t_pred.get("elementType") == "road"
    assert t_pred.get("elementId") == "A"
    assert t_pred.get("contactPoint") == "end", t_pred.attrib

    # Schema order: <link> must be the first child of a new <road>
    for road in (orphan, target):
        assert list(road).index(road.find("link")) == 0, \
            f"link must precede planView/lanes, got {[c.tag for c in road]}"
    print("PASS: reciprocal links + ASAM contactPoints + schema order")


def test_reverse_chain_contactpoints():
    """Chain orphan start -> target end: orphan predecessor cp='end',
    target successor cp='start'."""
    target = _xml_road("B", -100.0, 0.0, 0.0, 100.0)  # end (0,0)
    orphan = _xml_road("A", 0.0, 0.0, 0.0, 100.0)     # start (0,0)
    root = _root(target, orphan, junction_incoming="B")

    report = repair_orphan_roads(root, max_snap_m=5.0)
    assert report["repaired_connections"] == 1, report

    op = orphan.find("link").find("predecessor")
    assert op is not None and op.get("elementId") == "B"
    assert op.get("contactPoint") == "end", op.attrib
    ts = target.find("link").find("successor")
    assert ts is not None and ts.get("elementId") == "A"
    assert ts.get("contactPoint") == "start", ts.attrib
    print("PASS: reverse chain contactPoints")


def test_link_exists_successor_only_no_predecessor():
    """Regression: _link_exists used `pred.get` inside the successor loop,
    raising UnboundLocalError when no predecessor element existed."""
    road = _xml_road("B", 0.0, 0.0, 0.0, 10.0, with_link=[("successor", "A", "start")])
    assert _link_exists(road, "A") is True
    assert _link_exists(road, "Z") is False
    road2 = _xml_road("C", 0.0, 0.0, 0.0, 10.0, with_link=[("predecessor", "A", "end")])
    assert _link_exists(road2, "A") is True
    print("PASS: _link_exists successor-only regression")


def test_existing_slot_never_overwritten():
    """A target that already carries a predecessor keeps it; the pairing is
    refused (residual) instead of destroying the existing link."""
    orphan = _xml_road("A", 0.0, 0.0, 0.0, 100.0)
    target = _xml_road("B", 100.0, 0.0, 0.0, 100.0,
                       with_link=[("predecessor", "P", "end")])
    root = _root(orphan, target, junction_incoming="B")

    report = repair_orphan_roads(root, max_snap_m=5.0)
    assert report["repaired_connections"] == 0, report
    assert report["residual_unconnected"] == 1, report
    # The pre-existing link must survive untouched.
    pred = target.find("link").find("predecessor")
    assert pred.get("elementId") == "P", pred.attrib
    assert target.find("link").find("successor") is None
    assert orphan.find("link") is None, "orphan must not gain a one-sided link"
    print("PASS: existing slot never overwritten")


def test_duplicate_road_same_heading_rejected():
    """Two overlapping same-direction roads (duplicate) must be rejected:
    same-side endpoint pairs require near-OPPOSITE headings."""
    a = _xml_road("A", 0.0, 0.0, 0.0, 100.0)
    b = _xml_road("B", 0.0, 0.0, 0.0, 100.0)
    root = _root(a, b, junction_incoming="B")

    report = repair_orphan_roads(root, max_snap_m=5.0)
    assert report["repaired_connections"] == 0, report
    assert report["residual_unconnected"] == 1, report
    assert a.find("link") is None
    assert b.find("link") is None
    print("PASS: duplicate same-direction road rejected")


def test_orphan_default_threshold():
    from ultimate_pipeline.topology.orphan_road_repair import repair_orphan_roads as _r
    import inspect
    sig = inspect.signature(_r)
    assert sig.parameters["max_snap_m"].default == 5.0
    assert sig.parameters["max_heading_diff_deg"].default == 30.0
    assert sig.parameters["max_height_diff_m"].default == 1.0
    print("PASS: default thresholds 5.0 m / 30 deg / 1.0 m")


def test_strict_mode_raises_on_residuals():
    orphan = _xml_road("orphan1", 0.0, 0.0, 0.0, 50.0)
    root = _root(orphan)
    try:
        repair_orphan_roads(root, max_snap_m=5.0, strict=True)
        raise AssertionError("Should have raised RuntimeError")
    except RuntimeError as e:
        assert "residual unconnected orphans" in str(e)
    print("PASS: strict raises on residual orphans")


def test_zero_curvature_arc_is_straight():
    """A zero-curvature <arc> must not alter the heading (old code added
    `length` radians)."""
    road = ET.Element("road", {"id": "1", "junction": "-1"})
    planView = ET.SubElement(road, "planView")
    geom = ET.SubElement(planView, "geometry", {
        "s": "0.0", "x": "0.0", "y": "0.0", "hdg": "0.0", "length": "100.0"
    })
    ET.SubElement(geom, "arc", {"curvature": "0.0"})
    ends = _road_endpoints(road)
    assert abs(ends[1][0] - 100.0) < 0.01, f"expected straight x=100, got {ends}"
    assert abs(ends[1][1] - 0.0) < 0.01
    print("PASS: zero-curvature arc treated as straight")
