"""crosswalk_writer.py: wires real OSM footway=crossing data into XODR <object
type="crosswalk"> elements. crosswalk_schema.py only provides the CARLA-local
coordinate codec (world<->local corner transform); the actual OSM extraction,
road-matching, and outline construction did not exist before this.

Verified against the real pinned OSM source (2026-08-26): 179 footway=crossing
ways exist (0 crossing-tagged nodes) -- real, usable data.
"""
import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.crosswalk_writer import (
    extract_osm_crossings,
    project_crossing_to_local,
    nearest_point_on_road,
    match_crossing_to_road,
    crossing_outline_world,
    apply_crosswalks,
)


def _write_osm(tmp_path, ways_xml, nodes_xml=""):
    p = tmp_path / "test.osm"
    p.write_text(f'<osm version="0.6">{nodes_xml}{ways_xml}</osm>', encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------
# OSM extraction
# --------------------------------------------------------------------------

def test_extracts_footway_crossing_way_node_positions(tmp_path):
    osm = _write_osm(
        tmp_path,
        nodes_xml="""
            <node id="1" lat="48.7500" lon="11.4220"/>
            <node id="2" lat="48.7501" lon="11.4220"/>
        """,
        ways_xml="""
            <way id="10">
              <nd ref="1"/><nd ref="2"/>
              <tag k="footway" v="crossing"/>
            </way>
        """,
    )
    crossings = extract_osm_crossings(osm)
    assert len(crossings) == 1
    assert crossings[0]["way_id"] == "10"
    assert crossings[0]["nodes"] == [(11.4220, 48.7500), (11.4220, 48.7501)]


def test_non_crossing_footway_is_excluded(tmp_path):
    osm = _write_osm(
        tmp_path,
        nodes_xml='<node id="1" lat="48.75" lon="11.42"/><node id="2" lat="48.751" lon="11.421"/>',
        ways_xml="""
            <way id="11">
              <nd ref="1"/><nd ref="2"/>
              <tag k="footway" v="sidewalk"/>
            </way>
        """,
    )
    assert extract_osm_crossings(osm) == []


def test_way_with_missing_nodes_is_skipped_not_crashed(tmp_path):
    osm = _write_osm(
        tmp_path,
        nodes_xml='<node id="1" lat="48.75" lon="11.42"/>',
        ways_xml="""
            <way id="12">
              <nd ref="1"/><nd ref="999"/>
              <tag k="footway" v="crossing"/>
            </way>
        """,
    )
    assert extract_osm_crossings(osm) == []  # only 1/2 nodes resolvable -- not a usable line


# --------------------------------------------------------------------------
# Geometric matching (nearest point on a road's planView polyline)
# --------------------------------------------------------------------------

def _road(rid, points, junction="-1"):
    r = ET.Element("road", id=rid, junction=junction, length=str(len(points) * 10.0))
    pv = ET.SubElement(r, "planView")
    for i, (x, y) in enumerate(points[:-1]):
        nx, ny = points[i + 1]
        length = math.hypot(nx - x, ny - y)
        hdg = math.atan2(ny - y, nx - x)
        geom = ET.SubElement(pv, "geometry", s=str(i * 10.0), x=str(x), y=str(y), hdg=str(hdg), length=str(length))
        ET.SubElement(geom, "line")  # required for reference_pose_at_s to recognize the primitive
    return r


def test_nearest_point_on_road_returns_closest_point_and_distance():
    road = _road("1", [(0.0, 0.0), (10.0, 0.0)])
    dist, s, point = nearest_point_on_road(road, 5.0, 2.0)
    assert abs(dist - 2.0) < 1e-6
    assert abs(s - 5.0) < 1e-6


def test_match_crossing_to_road_picks_nearest_within_threshold():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", [(0.0, 0.0), (10.0, 0.0)]))
    root.append(_road("2", [(0.0, 100.0), (10.0, 100.0)]))  # far away
    match = match_crossing_to_road(root, (5.0, 1.0), max_dist_m=5.0)
    assert match is not None
    assert match["road"].get("id") == "1"
    assert abs(match["s"] - 5.0) < 1e-6


def test_match_crossing_to_road_returns_none_beyond_threshold():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", [(0.0, 0.0), (10.0, 0.0)]))
    match = match_crossing_to_road(root, (5.0, 50.0), max_dist_m=5.0)
    assert match is None


# --------------------------------------------------------------------------
# Outline construction (buffer a 2-point crossing line into a rectangle)
# --------------------------------------------------------------------------

def test_crossing_outline_is_a_buffered_rectangle():
    # A crossing line running along +y at x=5, length 4m -- buffered by 3m depth (+/-1.5m in x).
    outline = crossing_outline_world([(5.0, 0.0), (5.0, 4.0)], depth_m=3.0)
    assert len(outline) == 4
    xs = [c[0] for c in outline]
    ys = [c[1] for c in outline]
    assert min(xs) == pytest_approx(3.5) and max(xs) == pytest_approx(6.5)
    assert min(ys) == pytest_approx(0.0) and max(ys) == pytest_approx(4.0)


def pytest_approx(v, tol=1e-6):
    class _A:
        def __eq__(self, other):
            return abs(other - v) < tol
    return _A()


# --------------------------------------------------------------------------
# End-to-end writer
# --------------------------------------------------------------------------

def test_apply_crosswalks_inserts_object_for_a_real_matching_crossing():
    root = ET.Element("OpenDRIVE")
    road = _road("1", [(0.0, 0.0), (10.0, 0.0)])
    ET.SubElement(road, "type", s="0", type="town")
    root.append(road)

    crossings = [{"way_id": "10", "nodes_local": [(5.0, -1.5), (5.0, 1.5)]}]
    n = apply_crosswalks(root, crossings, max_match_dist_m=5.0, crossing_depth_m=3.0)
    assert n == 1
    objs = road.findall(".//objects/object[@type='crosswalk']")
    assert len(objs) == 1
    outline = objs[0].find("outline")
    assert outline is not None
    corners = outline.findall("cornerLocal")
    assert len(corners) == 4


def test_apply_crosswalks_skips_unmatched_crossings():
    root = ET.Element("OpenDRIVE")
    road = _road("1", [(0.0, 0.0), (10.0, 0.0)])
    root.append(road)
    crossings = [{"way_id": "99", "nodes_local": [(500.0, 500.0), (500.0, 503.0)]}]
    n = apply_crosswalks(root, crossings, max_match_dist_m=5.0)
    assert n == 0


def test_apply_crosswalks_real_pinned_data_end_to_end():
    OSM = "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
    CAND = ("campaigns/ingolstadt_cooked_perception_v1/candidate/"
            "ingolstadt_perception_map_of_record_20260819_160350.xodr")
    from ultimate_pipeline.domain_gap.local_registration import read_offset

    osm_crossings = extract_osm_crossings(OSM)
    assert len(osm_crossings) > 100  # matches the 179 verified this session

    root = ET.parse(CAND).getroot()
    offset = read_offset(root)
    for c in osm_crossings:
        c["nodes_local"] = project_crossing_to_local(c["nodes"], offset)

    n = apply_crosswalks(root, osm_crossings, max_match_dist_m=8.0)
    assert n > 0, "expected at least some real crossings to match a real road"
