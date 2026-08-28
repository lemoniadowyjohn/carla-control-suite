"""ultimate_pipeline/topology/roundabout_rebuilder.py -- lightweight roundabout DETECTION and
TAGGING (does not rewrite geometry, unlike the heavier RoundaboutReconstructor). Confirmed live
via stage_04_enrichment.py: RoundaboutRebuilder.tag_roundabouts() runs alongside
RoundaboutReconstructor.reconstruct(). Directly relevant to this branch's own namesake topic
(fix/post-audit-phase-e-junctions-roundabouts-20260803). Found as an orphaned .pyc in
tests/quality/__pycache__ (test_roundabout_invariants) while auditing the newly-surfaced
tests/quality/ directory; no roundabout_invariants-named source module was ever found, but the
underlying live modules (this file + roundabout_reconstructor.py) had zero coverage anywhere,
so this closes that gap directly rather than chasing the exact orphaned test's original name.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.roundabout_rebuilder import RoundaboutRebuilder


def _geom(s, x, y, hdg, length, arc=False):
    g = ET.Element("geometry", s=str(s), x=str(x), y=str(y), hdg=str(hdg), length=str(length))
    if arc:
        ET.SubElement(g, "arc", curvature="0.05")
    else:
        ET.SubElement(g, "line")
    return g


def _curvy_road(rid, length=20.0, one_way=True):
    """A short road with 2 arc geometries and driving lanes on only one side."""
    road = ET.Element("road", id=rid, length=str(length), junction="5")
    plan = ET.SubElement(road, "planView")
    plan.append(_geom(0, 0, 0, 0, length / 2, arc=True))
    plan.append(_geom(length / 2, length / 2, 0, 0.5, length / 2, arc=True))
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", id="-1", type="driving")
    if not one_way:
        left = ET.SubElement(section, "left")
        ET.SubElement(left, "lane", id="1", type="driving")
    return road


def _straight_road(rid, length=100.0):
    """A long, straight road with no arcs -- fails the short-and-curvy filter."""
    road = ET.Element("road", id=rid, length=str(length), junction="5")
    plan = ET.SubElement(road, "planView")
    plan.append(_geom(0, 0, 0, 0, length))
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", id="-1", type="driving")
    return road


def _junction_with_connections(jid, road_ids):
    j = ET.Element("junction", id=jid)
    # a 3-way roundabout needs >=3 connections referencing the candidate roads
    for i, rid in enumerate(road_ids):
        ET.SubElement(j, "connection", id=str(i), incomingRoad=rid, connectingRoad=rid)
    return j


def _xodr(roads, junctions):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    for j in junctions:
        root.append(j)
    return root


# ---------------------------------------------------------------------------
# _road_is_short_and_curvy
# ---------------------------------------------------------------------------

def test_short_curvy_road_passes():
    road = _curvy_road("1")
    assert RoundaboutRebuilder._road_is_short_and_curvy(road) is True


def test_long_road_fails_even_with_arcs():
    road = _curvy_road("1", length=200.0)
    assert RoundaboutRebuilder._road_is_short_and_curvy(road) is False


def test_short_straight_road_fails_not_curvy_enough():
    road = _straight_road("1", length=20.0)
    assert RoundaboutRebuilder._road_is_short_and_curvy(road) is False


# ---------------------------------------------------------------------------
# _road_is_one_way
# ---------------------------------------------------------------------------

def test_one_sided_driving_lanes_is_one_way():
    road = _curvy_road("1", one_way=True)
    assert RoundaboutRebuilder._road_is_one_way(road) is True


def test_both_sides_driving_lanes_is_not_one_way():
    road = _curvy_road("1", one_way=False)
    assert RoundaboutRebuilder._road_is_one_way(road) is False


def test_no_lanes_element_is_not_one_way():
    road = ET.Element("road", id="1", length="10.0")
    assert RoundaboutRebuilder._road_is_one_way(road) is False


def test_center_lane_id_zero_ignored_for_one_way_determination():
    # Only a center lane (id=0) on one side, no real driving lane anywhere -- neither
    # side counts, so has_left ^ has_right is False (both False).
    road = ET.Element("road", id="1", length="10.0")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", id="0", type="driving")  # id=0, explicitly excluded
    assert RoundaboutRebuilder._road_is_one_way(road) is False


# ---------------------------------------------------------------------------
# detect_roundabouts
# ---------------------------------------------------------------------------

def test_detect_roundabout_with_three_qualifying_roads():
    roads = [_curvy_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.detect_roundabouts(root)

    assert "5" in meta
    assert set(meta["5"]["roads"]) == {"1", "2", "3"}
    assert "center" in meta["5"]


def test_detect_roundabout_skips_junction_with_too_few_connections():
    roads = [_curvy_road(str(i)) for i in range(1, 3)]
    junction = _junction_with_connections("5", ["1", "2"])  # only 2, needs >= 3
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.detect_roundabouts(root)
    assert meta == {}


def test_detect_roundabout_skips_when_roads_dont_qualify():
    # 3 connections, but the roads are straight/long -- fail the curvy+one-way filter
    roads = [_straight_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.detect_roundabouts(root)
    assert meta == {}


def test_detect_roundabout_mixed_candidates_below_threshold_skipped():
    # only 2 of the 3 roads qualify -- below the "at least 3 candidates" bar
    roads = [_curvy_road("1"), _curvy_road("2"), _straight_road("3")]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.detect_roundabouts(root)
    assert meta == {}


def test_detect_roundabout_center_is_average_of_first_geometry_points():
    roads = [_curvy_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.detect_roundabouts(root)
    # all 3 roads' first geometry starts at (0, 0) per _curvy_road -- center must be (0, 0)
    assert meta["5"]["center"] == (0.0, 0.0)


def test_detect_roundabout_no_junctions_returns_empty():
    roads = [_curvy_road(str(i)) for i in range(1, 4)]
    root = _xodr(roads, [])
    assert RoundaboutRebuilder.detect_roundabouts(root) == {}


# ---------------------------------------------------------------------------
# tag_roundabouts
# ---------------------------------------------------------------------------

def test_tag_roundabouts_marks_junction_and_roads():
    roads = [_curvy_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.tag_roundabouts(root)

    assert junction.get("isRoundabout") == "true"
    for road in roads:
        type_el = road.find("type")
        assert type_el is not None
        assert type_el.get("type") == "roundabout"
    assert "5" in meta


def test_tag_roundabouts_creates_type_element_when_absent():
    road = _curvy_road("1")
    assert road.find("type") is None
    roads = [road, _curvy_road("2"), _curvy_road("3")]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    RoundaboutRebuilder.tag_roundabouts(root)

    type_el = road.find("type")
    assert type_el is not None
    assert type_el.get("type") == "roundabout"
    assert type_el.get("s") == "0.0"


def test_tag_roundabouts_overwrites_existing_type_element():
    road = _curvy_road("1")
    ET.SubElement(road, "type", s="0.0", type="motorway")  # pre-existing, different type
    roads = [road, _curvy_road("2"), _curvy_road("3")]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    RoundaboutRebuilder.tag_roundabouts(root)

    type_els = road.findall("type")
    assert len(type_els) == 1  # not duplicated
    assert type_els[0].get("type") == "roundabout"


def test_tag_roundabouts_no_qualifying_roundabout_leaves_map_untouched():
    roads = [_straight_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", ["1", "2", "3"])
    root = _xodr(roads, [junction])

    meta = RoundaboutRebuilder.tag_roundabouts(root)

    assert meta == {}
    assert junction.get("isRoundabout") is None
    for road in roads:
        assert road.find("type") is None
