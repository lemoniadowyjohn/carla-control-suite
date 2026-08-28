"""ultimate_pipeline/quality/check_carla_opendrive_compat.py -- offline gate that catches
XODR construct patterns known to hard-crash CARLA's OpenDRIVE importer. This is one of the 6
CRITICAL_MIRRORED_FILES drift-guarded between ultimate_pipeline/ and the submission mirror
(tests/phase_q/test_duplicate_module_drift.py) -- the highest safety tier in this codebase --
yet had ZERO test coverage anywhere. Found as an orphaned .pyc in tests/quality/__pycache__
(test_carla_opendrive_compat_gate.cpython-*.pyc with no matching .py source) while auditing the
newly-discovered tests/quality/ directory, itself only surfaced after fixing a pytest.ini
testpaths scope gap earlier today.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_carla_opendrive_compat import StrictCarlaOpendriveGate


def _minimal_road(rid="1", length="10.0", junction=None, geoms=None, lane_type="driving"):
    attrs = {"id": rid, "length": length}
    if junction is not None:
        attrs["junction"] = junction
    road = ET.Element("road", attrs)
    plan = ET.SubElement(road, "planView")
    for g in (geoms or [{"s": "0", "x": "0", "y": "0", "hdg": "0", "length": length, "prim": "line"}]):
        geom = ET.SubElement(plan, "geometry", s=g["s"], x=g["x"], y=g["y"], hdg=g["hdg"], length=g["length"])
        ET.SubElement(geom, g.get("prim", "line"))
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type=lane_type)
    ET.SubElement(lane, "width", sOffset="0.0", a="3.5", b="0.0", c="0.0", d="0.0")
    return road


def _valid_header():
    header = ET.Element("header")
    geo = ET.SubElement(header, "geoReference")
    geo.text = "+proj=tmerc +lat_0=0 +lon_0=9 +datum=WGS84"
    ET.SubElement(header, "offset", x="0.0", y="0.0", z="0.0", hdg="0.0")
    return header


def _xodr(*roads, header=True, junctions=()):
    root = ET.Element("OpenDRIVE")
    if header:
        root.append(_valid_header())
    for r in roads:
        root.append(r)
    for j in junctions:
        root.append(j)
    return root


def _codes(issues):
    return {i["code"] for i in issues}


# ---------------------------------------------------------------------------
# Root/header checks
# ---------------------------------------------------------------------------

def test_wrong_root_tag_is_a_fatal_error():
    root = ET.Element("NotOpenDRIVE")
    issues = StrictCarlaOpendriveGate.validate(root)
    assert _codes(issues) == {"root_tag"}


def test_missing_header_flagged():
    root = ET.Element("OpenDRIVE")
    root.append(_minimal_road())
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "missing_header" in _codes(issues)


def test_missing_georeference_flagged():
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "offset", x="0", y="0", z="0", hdg="0")
    root.append(_minimal_road())
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "missing_georeference" in _codes(issues)


def test_missing_offset_is_only_a_warning():
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    geo = ET.SubElement(header, "geoReference")
    geo.text = "+proj=tmerc"
    root.append(_minimal_road())
    issues = StrictCarlaOpendriveGate.validate(root)
    offset_issues = [i for i in issues if i["code"] == "missing_offset"]
    assert len(offset_issues) == 1
    assert offset_issues[0]["severity"] == "warn"


def test_valid_header_no_header_issues():
    root = _xodr(_minimal_road())
    issues = StrictCarlaOpendriveGate.validate(root)
    header_codes = {"missing_header", "missing_georeference", "missing_offset", "offset_missing_attr"}
    assert not (_codes(issues) & header_codes)


# ---------------------------------------------------------------------------
# Road indexing
# ---------------------------------------------------------------------------

def test_road_missing_id_flagged():
    road = ET.Element("road", length="10.0")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "road_missing_id" in _codes(issues)


def test_duplicate_road_id_flagged():
    root = _xodr(_minimal_road(rid="1"), _minimal_road(rid="1"))
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "duplicate_road_id" in _codes(issues)


def test_no_roads_at_all_short_circuits_cleanly():
    root = _xodr()
    issues = StrictCarlaOpendriveGate.validate(root)
    assert issues == []  # nothing to check further, no crash


# ---------------------------------------------------------------------------
# Road-level geometry checks
# ---------------------------------------------------------------------------

def test_nonpositive_road_length_flagged():
    road = _minimal_road(length="0.0")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "road_length_nonpositive" in _codes(issues)


def test_missing_planview_flagged():
    road = ET.Element("road", id="1", length="10.0")
    lanes = ET.SubElement(road, "lanes")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "missing_planView" in _codes(issues)


def test_planview_with_no_geometry_flagged():
    road = ET.Element("road", id="1", length="10.0")
    ET.SubElement(road, "planView")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "missing_geometry" in _codes(issues)


def test_geometry_missing_s_flagged():
    road = ET.Element("road", id="1", length="10.0")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", x="0", y="0", hdg="0", length="10.0")  # no s=
    ET.SubElement(geom, "line")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "geometry_missing_s" in _codes(issues)


def test_geometry_s_not_increasing_flagged():
    road = _minimal_road(geoms=[
        {"s": "5", "x": "0", "y": "0", "hdg": "0", "length": "5.0", "prim": "line"},
        {"s": "5", "x": "5", "y": "0", "hdg": "0", "length": "5.0", "prim": "line"},  # same s
    ])
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "geometry_s_not_increasing" in _codes(issues)


def test_geometry_negative_s_flagged():
    road = _minimal_road(geoms=[{"s": "-1.0", "x": "0", "y": "0", "hdg": "0", "length": "10.0", "prim": "line"}])
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "geometry_s_negative" in _codes(issues)


def test_geometry_nonpositive_length_flagged():
    road = _minimal_road(geoms=[{"s": "0", "x": "0", "y": "0", "hdg": "0", "length": "0.0", "prim": "line"}])
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "geometry_length_invalid" in _codes(issues)


def test_geometry_nonfinite_coordinate_flagged():
    road = ET.Element("road", id="1", length="10.0")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", s="0", x="nan", y="0", hdg="0", length="10.0")
    ET.SubElement(geom, "line")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "geometry_nonfinite" in _codes(issues)


def test_unsupported_primitive_is_a_warning():
    road = ET.Element("road", id="1", length="10.0")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    ET.SubElement(geom, "someUnknownPrimitive")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    matches = [i for i in issues if i["code"] == "geometry_unsupported_primitive"]
    assert len(matches) == 1
    assert matches[0]["severity"] == "warn"


def test_road_length_mismatch_vs_geometry_sum_flagged():
    # declared length 100, but geometry only sums to 10 -- large mismatch
    road = _minimal_road(length="100.0", geoms=[
        {"s": "0", "x": "0", "y": "0", "hdg": "0", "length": "10.0", "prim": "line"},
    ])
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "road_length_mismatch" in _codes(issues)


def test_road_length_matches_geometry_sum_no_mismatch():
    road = _minimal_road(length="10.0")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "road_length_mismatch" not in _codes(issues)


def test_valid_single_geometry_road_has_no_geometry_issues():
    road = _minimal_road()
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    geom_codes = {c for c in _codes(issues) if c.startswith("geometry_") or c.startswith("road_")}
    assert geom_codes == set()


# ---------------------------------------------------------------------------
# Elevation checks
# ---------------------------------------------------------------------------

def test_elevation_missing_coefficient_flagged():
    road = _minimal_road()
    profile = ET.SubElement(road, "elevationProfile")
    ET.SubElement(profile, "elevation", s="0", a="0", b="0", c="0")  # missing "d"
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "elevation_missing_attr" in _codes(issues)


def test_elevation_nonfinite_flagged():
    road = _minimal_road()
    profile = ET.SubElement(road, "elevationProfile")
    ET.SubElement(profile, "elevation", s="0", a="nan", b="0", c="0", d="0")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "elevation_nonfinite" in _codes(issues)


# ---------------------------------------------------------------------------
# Lane-section checks
# ---------------------------------------------------------------------------

def test_missing_lanes_element_flagged():
    road = ET.Element("road", id="1", length="10.0")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    ET.SubElement(geom, "line")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "missing_lanes" in _codes(issues)


def test_missing_center_lane_flagged():
    road = _minimal_road()
    section = road.find("lanes/laneSection")
    section.remove(section.find("center"))
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "missing_center_lane" in _codes(issues)


def test_duplicate_lane_id_is_a_warning():
    road = _minimal_road()
    right = road.find("lanes/laneSection/right")
    ET.SubElement(right, "lane", id="-1", type="driving")  # duplicate of the existing -1
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    matches = [i for i in issues if i["code"] == "duplicate_lane_id"]
    assert len(matches) == 1
    assert matches[0]["severity"] == "warn"


def test_driving_lane_missing_width_flagged():
    road = _minimal_road()
    lane = road.find("lanes/laneSection/right/lane")
    lane.remove(lane.find("width"))
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "driving_lane_missing_width" in _codes(issues)


def test_lane_width_nonpositive_flagged():
    road = _minimal_road()
    width = road.find("lanes/laneSection/right/lane/width")
    width.set("a", "0.0")
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "lane_width_nonpositive" in _codes(issues)


def test_non_driving_lane_without_width_not_flagged():
    road = _minimal_road(lane_type="sidewalk")
    lane = road.find("lanes/laneSection/right/lane")
    lane.remove(lane.find("width"))
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "driving_lane_missing_width" not in _codes(issues)


# ---------------------------------------------------------------------------
# Junction checks
# ---------------------------------------------------------------------------

def test_junction_connection_missing_incoming_road_flagged():
    road = _minimal_road(rid="1", junction="5")
    junction = ET.Element("junction", id="5")
    ET.SubElement(junction, "connection", id="0", incomingRoad="99", connectingRoad="1")
    root = _xodr(road, junctions=(junction,))
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "junction_missing_incoming" in _codes(issues)


def test_junction_connection_missing_connecting_road_flagged():
    road1 = _minimal_road(rid="1")
    junction = ET.Element("junction", id="5")
    ET.SubElement(junction, "connection", id="0", incomingRoad="1", connectingRoad="99")
    root = _xodr(road1, junctions=(junction,))
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "junction_missing_connecting" in _codes(issues)


def test_connecting_road_missing_junction_attr_is_a_warning():
    road1 = _minimal_road(rid="1")
    road2 = _minimal_road(rid="2")  # no junction attr set on this connecting road
    junction = ET.Element("junction", id="5")
    conn = ET.SubElement(junction, "connection", id="0", incomingRoad="1", connectingRoad="2")
    ET.SubElement(conn, "laneLink", **{"from": "-1", "to": "-1"})
    root = _xodr(road1, road2, junctions=(junction,))
    issues = StrictCarlaOpendriveGate.validate(root)
    matches = [i for i in issues if i["code"] == "connectingRoad_missing_junction_attr"]
    assert len(matches) == 1
    assert matches[0]["severity"] == "warn"


def test_connecting_road_wrong_junction_attr_flagged():
    road1 = _minimal_road(rid="1")
    road2 = _minimal_road(rid="2", junction="99")  # wrong junction id
    junction = ET.Element("junction", id="5")
    conn = ET.SubElement(junction, "connection", id="0", incomingRoad="1", connectingRoad="2")
    ET.SubElement(conn, "laneLink", **{"from": "-1", "to": "-1"})
    root = _xodr(road1, road2, junctions=(junction,))
    issues = StrictCarlaOpendriveGate.validate(root)
    assert "connectingRoad_wrong_junction" in _codes(issues)


def test_junction_connection_missing_lanelink_is_a_warning():
    road1 = _minimal_road(rid="1")
    road2 = _minimal_road(rid="2", junction="5")
    junction = ET.Element("junction", id="5")
    ET.SubElement(junction, "connection", id="0", incomingRoad="1", connectingRoad="2")  # no laneLink
    root = _xodr(road1, road2, junctions=(junction,))
    issues = StrictCarlaOpendriveGate.validate(root)
    matches = [i for i in issues if i["code"] == "junction_missing_laneLink"]
    assert len(matches) == 1
    assert matches[0]["severity"] == "warn"


def test_well_formed_junction_no_junction_issues():
    road1 = _minimal_road(rid="1")
    road2 = _minimal_road(rid="2", junction="5")
    junction = ET.Element("junction", id="5")
    conn = ET.SubElement(junction, "connection", id="0", incomingRoad="1", connectingRoad="2")
    ET.SubElement(conn, "laneLink", **{"from": "-1", "to": "-1"})
    root = _xodr(road1, road2, junctions=(junction,))
    issues = StrictCarlaOpendriveGate.validate(root)
    junction_codes = {c for c in _codes(issues) if "junction" in c or "connectingRoad" in c}
    assert junction_codes == set()


# ---------------------------------------------------------------------------
# Full clean map -- zero issues end to end
# ---------------------------------------------------------------------------

def test_fully_valid_map_yields_zero_issues():
    road = _minimal_road()
    root = _xodr(road)
    issues = StrictCarlaOpendriveGate.validate(root)
    assert issues == []
