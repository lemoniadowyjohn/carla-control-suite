"""ultimate_pipeline/topology/roundabout_reconstructor.py -- the heavier of the two roundabout
modules: detects roundabout clusters and REBUILDS them as a clean circular road (unlike
RoundaboutRebuilder, which only tags roads/junctions in place). Directly this branch's own
namesake topic (fix/post-audit-phase-e-junctions-roundabouts-20260803). Confirmed live via
stage_04_enrichment.py's RoundaboutReconstructor.reconstruct() call. Found as an orphaned .pyc
in tests/quality/__pycache__ (test_roundabout_invariants) while auditing the newly-surfaced
tests/quality/ directory; no roundabout_invariants-named source module was ever found, but this
underlying live module had zero coverage anywhere, so this closes that gap directly.

NOTE (found while reading the source, not fixed here): ENABLE_ROUNDABOUT_RECONSTRUCTION defaults
False across every release profile in settings.py -- this module is disabled by default in the
live pipeline; only the lighter RoundaboutRebuilder.tag_roundabouts() runs unconditionally. Not
a bug -- matches this session's established caution around aggressive geometry-mutation
features (see the ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING negative-result experiment) -- but worth
knowing given the branch's own name references roundabout work.

Scope: covers the pure detection/geometry-building helpers (_RoundaboutDetector.*, _new_id,
_build_roundabout, _estimate_roundabout_elevation, _angle) plus end-to-end reconstruct() for the
disabled/no-detection/successful paths. The elevation-smoothing internals
(_smooth_elevation_around_roundabout, _ensure_elevation_transition,
_smooth_elevation_near_connection, _smooth_elevation_near_roundabout) are each independently
wrapped in try/except at their call sites and explicitly documented as best-effort/non-critical
-- exercised indirectly via the end-to-end tests (confirmed not to crash) rather than unit-tested
in isolation, to keep this pass proportionate to their actual safety weight.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.roundabout_reconstructor import (
    RoundaboutReconstructor,
    _RoundaboutDetector,
)


def _geom(s, x, y, hdg, length, arc=False, curvature=0.05):
    g = ET.Element("geometry", s=str(s), x=str(x), y=str(y), hdg=str(hdg), length=str(length))
    if arc:
        ET.SubElement(g, "arc", curvature=str(curvature))
    else:
        ET.SubElement(g, "line")
    return g


def _curvy_road(rid, length=20.0, one_way=True, x0=0.0, y0=0.0):
    road = ET.Element("road", id=rid, length=str(length), junction="5")
    plan = ET.SubElement(road, "planView")
    plan.append(_geom(0, x0, y0, 0, length / 2, arc=True))
    plan.append(_geom(length / 2, x0 + length / 2, y0, 0.5, length / 2, arc=True))
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


def _junction_with_connections(jid, road_pairs):
    """road_pairs: list of (incomingRoad, connectingRoad) tuples."""
    j = ET.Element("junction", id=jid)
    for i, (inc, con) in enumerate(road_pairs):
        ET.SubElement(j, "connection", id=str(i), incomingRoad=inc, connectingRoad=con)
    return j


def _xodr(roads, junctions):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    for j in junctions:
        root.append(j)
    return root


# ---------------------------------------------------------------------------
# _RoundaboutDetector._road_is_short_and_curvy (tuple return with reason codes)
# ---------------------------------------------------------------------------

def test_short_curvy_road_passes_via_arc_count():
    road = _curvy_road("1")
    ok, reason = _RoundaboutDetector._road_is_short_and_curvy(road)
    assert ok is True
    assert reason == "arc_count"


def test_too_long_road_rejected_with_reason():
    road = _curvy_road("1", length=200.0)
    ok, reason = _RoundaboutDetector._road_is_short_and_curvy(road)
    assert ok is False
    assert reason == "too_long"


def test_short_straight_road_rejected_not_curvy():
    road = _straight_road("1", length=20.0)
    ok, reason = _RoundaboutDetector._road_is_short_and_curvy(road)
    assert ok is False
    assert reason == "not_curvy"


def test_short_road_qualifies_via_heading_change_without_arcs():
    # 4+ geometries with cumulative heading change >= 45 deg, but no <arc> children at all
    road = ET.Element("road", id="1", length="20.0", junction="5")
    plan = ET.SubElement(road, "planView")
    for i, hdg_deg in enumerate((0, 15, 30, 50)):
        plan.append(_geom(i * 5, i * 5, 0, math.radians(hdg_deg), 5.0, arc=False))
    ok, reason = _RoundaboutDetector._road_is_short_and_curvy(road)
    assert ok is True
    assert reason == "heading_change"


# ---------------------------------------------------------------------------
# _RoundaboutDetector._road_is_one_way
# ---------------------------------------------------------------------------

def test_one_sided_driving_lanes_is_one_way():
    road = _curvy_road("1", one_way=True)
    assert _RoundaboutDetector._road_is_one_way(road) is True


def test_both_sides_driving_lanes_is_not_one_way():
    road = _curvy_road("1", one_way=False)
    assert _RoundaboutDetector._road_is_one_way(road) is False


def test_no_lanes_element_is_not_one_way():
    road = ET.Element("road", id="1", length="10.0")
    assert _RoundaboutDetector._road_is_one_way(road) is False


# ---------------------------------------------------------------------------
# _RoundaboutDetector.detect
# ---------------------------------------------------------------------------

def test_detect_finds_qualifying_roundabout_with_metadata():
    roads = [_curvy_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    detected, meta = _RoundaboutDetector.detect(root)

    assert "5" in detected
    assert set(detected["5"]["roads"]) == {"1", "2", "3"}
    assert meta["candidate_junctions_checked"] == 1
    assert "roundabouts_reconstructed" not in meta  # only reconstruct() adds this key


def test_detect_records_rejection_reason_not_enough_connections():
    roads = [_curvy_road(str(i)) for i in range(1, 3)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2")])  # only 2
    root = _xodr(roads, [junction])

    detected, meta = _RoundaboutDetector.detect(root)

    assert detected == {}
    assert meta["rejections"]["not_enough_connections"] == 1


def test_detect_records_rejection_reason_too_long():
    roads = [_curvy_road(str(i), length=200.0) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    detected, meta = _RoundaboutDetector.detect(root)

    assert detected == {}
    assert meta["rejections"]["too_long"] >= 1


def test_detect_records_rejection_reason_not_one_way():
    roads = [_curvy_road(str(i), one_way=False) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    detected, meta = _RoundaboutDetector.detect(root)

    assert detected == {}
    assert meta["rejections"]["not_one_way"] >= 1


# ---------------------------------------------------------------------------
# RoundaboutReconstructor._new_id
# ---------------------------------------------------------------------------

def test_new_id_is_one_more_than_max_existing():
    root = _xodr([ET.Element("road", id="5"), ET.Element("road", id="12")], [])
    assert RoundaboutReconstructor._new_id(root) == "13"


def test_new_id_defaults_to_10000_when_no_roads():
    root = _xodr([], [])
    assert RoundaboutReconstructor._new_id(root) == "10000"


def test_new_id_ignores_non_numeric_ids():
    root = _xodr([ET.Element("road", id="abc"), ET.Element("road", id="3")], [])
    assert RoundaboutReconstructor._new_id(root) == "4"


# ---------------------------------------------------------------------------
# RoundaboutReconstructor._build_roundabout
# ---------------------------------------------------------------------------

def test_build_roundabout_produces_circular_arc_geometry():
    road_map = {"1": _curvy_road("1")}
    new_road = RoundaboutReconstructor._build_roundabout("999", "5", 0.0, 0.0, 10.0, ["1"], road_map)

    assert new_road.get("id") == "999"
    assert new_road.get("junction") == "5"
    length = float(new_road.get("length"))
    assert abs(length - 2 * math.pi * 10.0) < 1e-3

    geom = new_road.find("planView/geometry")
    assert geom is not None
    arc = geom.find("arc")
    assert arc is not None
    assert abs(float(arc.get("curvature")) - (1.0 / 10.0)) < 1e-6


def test_build_roundabout_has_center_lane_and_one_driving_lane():
    road_map = {}
    new_road = RoundaboutReconstructor._build_roundabout("999", "5", 0.0, 0.0, 10.0, [], road_map)

    section = new_road.find("lanes/laneSection")
    center_lane = section.find("center/lane")
    assert center_lane.get("id") == "0"
    driving_lane = section.find("right/lane")
    assert driving_lane.get("id") == "-1"
    assert driving_lane.get("type") == "driving"
    width = driving_lane.find("width")
    assert float(width.get("a")) > 0.0


def test_build_roundabout_no_self_referential_link():
    road_map = {}
    new_road = RoundaboutReconstructor._build_roundabout("999", "5", 0.0, 0.0, 10.0, [], road_map)
    assert new_road.find("link") is None


# ---------------------------------------------------------------------------
# RoundaboutReconstructor._estimate_roundabout_elevation
# ---------------------------------------------------------------------------

def test_estimate_elevation_averages_connected_roads():
    road1 = ET.Element("road", id="1")
    ep1 = ET.SubElement(road1, "elevationProfile")
    ET.SubElement(ep1, "elevation", s="0", a="10.0", b="0", c="0", d="0")
    road2 = ET.Element("road", id="2")
    ep2 = ET.SubElement(road2, "elevationProfile")
    ET.SubElement(ep2, "elevation", s="0", a="20.0", b="0", c="0", d="0")
    road_map = {"1": road1, "2": road2}

    z = RoundaboutReconstructor._estimate_roundabout_elevation(["1", "2"], road_map)
    assert z == 15.0


def test_estimate_elevation_no_elevation_data_defaults_zero():
    road1 = ET.Element("road", id="1")  # no elevationProfile at all
    road_map = {"1": road1}
    z = RoundaboutReconstructor._estimate_roundabout_elevation(["1"], road_map)
    assert z == 0.0


# ---------------------------------------------------------------------------
# RoundaboutReconstructor._angle
# ---------------------------------------------------------------------------

def test_angle_missing_road_returns_zero():
    root = _xodr([], [])
    assert RoundaboutReconstructor._angle(root, "nonexistent", 0.0, 0.0) == 0.0


def test_angle_no_geometry_returns_zero():
    road = ET.Element("road", id="1")
    ET.SubElement(road, "planView")  # no geometry children
    root = _xodr([road], [])
    assert RoundaboutReconstructor._angle(root, "1", 0.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# RoundaboutReconstructor.reconstruct -- end to end
# ---------------------------------------------------------------------------

def test_reconstruct_disabled_by_settings_returns_empty(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", False, raising=False)

    roads = [_curvy_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    result = RoundaboutReconstructor.reconstruct(root)
    assert result == {}


def test_reconstruct_no_roundabouts_detected_returns_meta_only(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True, raising=False)

    roads = [_straight_road(str(i)) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    result = RoundaboutReconstructor.reconstruct(root)
    assert result["_meta"]["roundabouts_reconstructed"] == 0
    assert "5" not in result


def test_reconstruct_successful_roundabout_adds_new_circular_road(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True, raising=False)

    roads = [_curvy_road(str(i), x0=float(i) * 2, y0=0.0) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    result = RoundaboutReconstructor.reconstruct(root)

    assert result["_meta"]["roundabouts_reconstructed"] == 1
    assert "5" in result
    new_id = result["5"]["new_road"]
    new_road = root.find(f"./road[@id='{new_id}']")
    assert new_road is not None
    assert new_road.get("junction") == "5"


def test_reconstruct_rewrites_junction_connections_to_new_road(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True, raising=False)

    roads = [_curvy_road(str(i), x0=float(i) * 2, y0=0.0) for i in range(1, 4)]
    junction = _junction_with_connections("5", [("1", "1"), ("2", "2"), ("3", "3")])
    root = _xodr(roads, [junction])

    result = RoundaboutReconstructor.reconstruct(root)
    new_id = result["5"]["new_road"]

    for conn in junction.findall("connection"):
        assert conn.get("connectingRoad") == new_id
        assert conn.get("contactPoint") in ("start", "end")


def test_reconstruct_orphans_old_roads_not_referenced_after_rewrite(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True, raising=False)

    # Realistic roundabout topology: 3 curvy "core" roads (the roundabout's own connector
    # segments, referenced as connectingRoad) plus 3 separate, non-curvy "incoming" roads
    # (external approach roads, referenced as incomingRoad). Only connectingRoad gets
    # rewritten to new_id, so the core roads become fully unreferenced and orphan-eligible;
    # a self-referencing incomingRoad==connectingRoad fixture (as in the sibling test) would
    # never satisfy the orphan condition, since incomingRoad is never rewritten.
    core_roads = [_curvy_road(str(i), x0=float(i) * 2, y0=0.0) for i in range(1, 4)]
    incoming_roads = [_straight_road(str(i)) for i in (10, 11, 12)]
    junction = _junction_with_connections(
        "5", [("10", "1"), ("11", "2"), ("12", "3")]
    )
    root = _xodr(core_roads + incoming_roads, [junction])

    RoundaboutReconstructor.reconstruct(root)

    # core roads are no longer referenced by any connection (connectingRoad rewritten to
    # new_id, and none of them were ever an incomingRoad) -> orphaned, per the module's own
    # "never delete, just orphan" safety policy.
    for road in core_roads:
        assert road.get("junction") == "-1"
        driving_lanes_remaining = road.findall(".//lane[@type='driving']")
        assert driving_lanes_remaining == []

    # the incoming roads are still referenced (incomingRoad was never rewritten) -> untouched.
    for road in incoming_roads:
        assert road.get("junction") == "5"


def test_reconstruct_does_not_crash_when_no_junction_element_matches(monkeypatch):
    # detect() can only find roundabouts anchored to a real <junction>, but guard against a
    # future refactor where a detected jid doesn't resolve -- reconstruct() must skip cleanly.
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_ROUNDABOUT_RECONSTRUCTION", True, raising=False)

    root = _xodr([], [])
    result = RoundaboutReconstructor.reconstruct(root)
    assert result["_meta"]["roundabouts_reconstructed"] == 0
