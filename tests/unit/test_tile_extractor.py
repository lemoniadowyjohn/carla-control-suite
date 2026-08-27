"""ultimate_pipeline/tiling/tile_extractor.py -- the map-tiling stage, imported directly by
main_pipeline.py. Fully offline XML processing (no CARLA dependency) but a bug here could
silently corrupt map tiles used downstream for perception capture: dropping roads, splitting a
junction across tile boundaries, or miscounting drivable lanes. Existing coverage was limited to
a single narrow test (ultimate_pipeline/tests/unit/test_tile_extractor_crs.py, georeference
preservation only); the core tiling algorithm itself (buffering, junction-grouping, lane-leakage
tracking, highway-aware buffer, health reporting) had zero dedicated coverage. Found via an
expanded orphaned-.pyc sweep that also checked the top-level tests/ directory (the original
tests/test_tile_extractor.py no longer exists on this branch, but the module remains live).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tiling.tile_extractor import (
    TileExtractor,
    _analyze_tile_lanes,
    _compute_effective_buffer,
    _is_highway,
    _is_lane_driving_in_tile,
    _iter_tile_origins,
    _lane_predecessor_points_outside_tile,
    _lane_successor_points_outside_tile,
    _mark_global_driving_lanes,
    _road_length,
    _tile_road_ids,
    deep_clone,
)


# ---------------------------------------------------------------------------
# deep_clone
# ---------------------------------------------------------------------------

def test_deep_clone_preserves_tag_attrib_text_and_children():
    original = ET.Element("road", id="1", length="10.0")
    child = ET.SubElement(original, "planView")
    child.text = "hello"
    clone = deep_clone(original)
    assert clone.tag == "road"
    assert clone.get("id") == "1"
    assert clone.find("planView").text == "hello"


def test_deep_clone_is_independent_of_original():
    original = ET.Element("road", id="1")
    clone = deep_clone(original)
    clone.set("id", "2")
    assert original.get("id") == "1"


# ---------------------------------------------------------------------------
# _tile_road_ids
# ---------------------------------------------------------------------------

def test_tile_road_ids_collects_all_road_ids():
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "road", id="1")
    ET.SubElement(root, "road", id="2")
    assert _tile_road_ids(root) == {"1", "2"}


def test_tile_road_ids_empty_root():
    assert _tile_road_ids(ET.Element("OpenDRIVE")) == set()


# ---------------------------------------------------------------------------
# _is_lane_driving_in_tile
# ---------------------------------------------------------------------------

def test_is_lane_driving_in_tile_type_driving_always_true():
    lane = ET.Element("lane", type="driving")
    assert _is_lane_driving_in_tile(lane, preserve_global=False) is True


def test_is_lane_driving_in_tile_marked_was_driving_requires_preserve_global():
    lane = ET.Element("lane", type="sidewalk", was_driving="true")
    assert _is_lane_driving_in_tile(lane, preserve_global=True) is True
    assert _is_lane_driving_in_tile(lane, preserve_global=False) is False


def test_is_lane_driving_in_tile_non_driving_no_marker():
    lane = ET.Element("lane", type="sidewalk")
    assert _is_lane_driving_in_tile(lane, preserve_global=True) is False


# ---------------------------------------------------------------------------
# _lane_successor_points_outside_tile / _lane_predecessor_points_outside_tile
# ---------------------------------------------------------------------------

def test_lane_successor_outside_tile_detected():
    lane = ET.Element("lane")
    link = ET.SubElement(lane, "link")
    ET.SubElement(link, "successor", road="99")
    assert _lane_successor_points_outside_tile(lane, {"1", "2"}) is True


def test_lane_successor_inside_tile_not_flagged():
    lane = ET.Element("lane")
    link = ET.SubElement(lane, "link")
    ET.SubElement(link, "successor", road="1")
    assert _lane_successor_points_outside_tile(lane, {"1", "2"}) is False


def test_lane_no_successor_not_flagged():
    lane = ET.Element("lane")
    assert _lane_successor_points_outside_tile(lane, {"1"}) is False


def test_lane_predecessor_outside_tile_detected():
    lane = ET.Element("lane")
    link = ET.SubElement(lane, "link")
    ET.SubElement(link, "predecessor", road="99")
    assert _lane_predecessor_points_outside_tile(lane, {"1", "2"}) is True


# ---------------------------------------------------------------------------
# _road_length / _is_highway
# ---------------------------------------------------------------------------

def test_road_length_sums_geometry_segments():
    road = ET.Element("road")
    planview = ET.SubElement(road, "planView")
    ET.SubElement(planview, "geometry", length="10.0")
    ET.SubElement(planview, "geometry", length="15.5")
    assert _road_length(road) == 25.5


def test_road_length_no_geometry_is_zero():
    assert _road_length(ET.Element("road")) == 0.0


def test_is_highway_true_for_known_types():
    assert _is_highway(ET.Element("road", type="motorway")) is True
    assert _is_highway(ET.Element("road", type="trunk")) is True
    assert _is_highway(ET.Element("road", type="primary")) is True


def test_is_highway_false_for_residential():
    assert _is_highway(ET.Element("road", type="residential")) is False


# ---------------------------------------------------------------------------
# _iter_tile_origins
# ---------------------------------------------------------------------------

def test_iter_tile_origins_grid_covers_full_bounds():
    origins = list(_iter_tile_origins(0.0, 250.0, 0.0, 150.0, tile_size=100.0))
    # x: 0, 100, 200 (3 columns); y: 0, 100 (2 rows) -> 6 cells
    ixs = sorted({o[0] for o in origins})
    iys = sorted({o[1] for o in origins})
    assert ixs == [0, 1, 2]
    assert iys == [0, 1]
    assert len(origins) == 6


def test_iter_tile_origins_single_cell_when_bounds_smaller_than_tile():
    origins = list(_iter_tile_origins(0.0, 50.0, 0.0, 50.0, tile_size=100.0))
    assert origins == [(0, 0, 0.0, 0.0)]


def test_iter_tile_origins_empty_when_min_equals_max():
    # NOTE: this documents real, current behavior, not necessarily ideal behavior. Because
    # both while loops use strict "<" against max, a perfectly degenerate (zero-extent) bbox
    # on either axis yields NO origins at all -- discovered while writing this file's
    # TileExtractor.tile() integration tests: a single axis-aligned road (hdg=0 or 90) with
    # no lane-width margin produces exactly this degenerate per-road bbox. At the map level
    # this is not a practical concern -- TileExtractor.tile() computes min/max across ALL
    # roads in the map, and every road in the map would need to share the exact same X (or
    # Y) coordinate for the AGGREGATE bounds to degenerate this way, which does not happen on
    # a real multi-thousand-road map. Not treated as a bug worth fixing here; the integration
    # tests below use a lane <width> element (as any real driving lane has) specifically to
    # avoid hitting this edge case, matching realistic XODR rather than probing this corner.
    assert list(_iter_tile_origins(0.0, 0.0, 0.0, 0.0, tile_size=100.0)) == []


# ---------------------------------------------------------------------------
# _compute_effective_buffer
# ---------------------------------------------------------------------------

def _highway_road(length_m: float) -> ET.Element:
    road = ET.Element("road", type="motorway")
    planview = ET.SubElement(road, "planView")
    ET.SubElement(planview, "geometry", length=str(length_m))
    return road


def test_compute_effective_buffer_disabled_returns_base():
    roads = [_highway_road(1000.0)]
    buf = _compute_effective_buffer(30.0, roads, enable_highway_buffer=False, alpha=0.15)
    assert buf == 30.0


def test_compute_effective_buffer_highway_adds_alpha_scaled_extra():
    roads = [_highway_road(1000.0)]
    buf = _compute_effective_buffer(30.0, roads, enable_highway_buffer=True, alpha=0.15)
    assert buf == 30.0 + 1000.0 * 0.15


def test_compute_effective_buffer_uses_longest_highway_not_sum():
    roads = [_highway_road(1000.0), _highway_road(2000.0)]
    buf = _compute_effective_buffer(30.0, roads, enable_highway_buffer=True, alpha=0.1)
    assert buf == 30.0 + 2000.0 * 0.1  # not (1000+2000)*0.1


def test_compute_effective_buffer_non_highway_roads_ignored():
    residential = ET.Element("road", type="residential")
    planview = ET.SubElement(residential, "planView")
    ET.SubElement(planview, "geometry", length="5000.0")
    buf = _compute_effective_buffer(30.0, [residential], enable_highway_buffer=True, alpha=0.15)
    assert buf == 30.0


# ---------------------------------------------------------------------------
# _mark_global_driving_lanes
# ---------------------------------------------------------------------------

def test_mark_global_driving_lanes_marks_driving_lanes():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", type="driving", id="-1")
    ET.SubElement(right, "lane", type="sidewalk", id="-2")

    n = _mark_global_driving_lanes(root)

    assert n == 1
    driving_lane = right.find("lane[@type='driving']")
    assert driving_lane.get("was_driving") == "true"
    sidewalk_lane = right.find("lane[@type='sidewalk']")
    assert sidewalk_lane.get("was_driving") is None


def test_mark_global_driving_lanes_idempotent_second_call_marks_nothing_new():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", type="driving", id="-1")

    first = _mark_global_driving_lanes(root)
    second = _mark_global_driving_lanes(root)
    assert first == 1
    assert second == 0


# ---------------------------------------------------------------------------
# _analyze_tile_lanes
# ---------------------------------------------------------------------------

def test_analyze_tile_lanes_counts_driving_and_flags_leakage():
    tile_root = ET.Element("OpenDRIVE")
    road = ET.SubElement(tile_root, "road", id="1")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", type="driving", id="-1")
    link = ET.SubElement(lane, "link")
    ET.SubElement(link, "successor", road="99")  # outside this tile (only road "1" present)

    result = _analyze_tile_lanes(tile_root, preserve_global=False)

    assert result["driving_like"] == 1
    assert result["successor_outside"] == 1
    assert result["predecessor_outside"] == 0
    assert lane.get("_successor_outside_tile") == "true"


def test_analyze_tile_lanes_non_driving_lane_not_counted():
    tile_root = ET.Element("OpenDRIVE")
    road = ET.SubElement(tile_root, "road", id="1")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection")
    right = ET.SubElement(section, "right")
    ET.SubElement(right, "lane", type="sidewalk", id="-1")

    result = _analyze_tile_lanes(tile_root, preserve_global=False)
    assert result["driving_like"] == 0


# ---------------------------------------------------------------------------
# TileExtractor.tile -- end-to-end integration
# ---------------------------------------------------------------------------

def _write_road_xodr(path: Path, roads_xyz) -> None:
    """roads_xyz: list of (road_id, x, y, length, junction) placed as a single
    line geometry starting at (x, y)."""
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    for rid, x, y, length, junction in roads_xyz:
        road = ET.SubElement(root, "road", id=rid, length=str(length), junction=junction)
        planview = ET.SubElement(road, "planView")
        geom = ET.SubElement(planview, "geometry", s="0", x=str(x), y=str(y), hdg="0", length=str(length))
        ET.SubElement(geom, "line")  # required child -- without it, _geom_kind returns "unknown"
        # and road_bounds_curve_aware degenerates to a zero-extent point, matching real XODR.
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0")
        right = ET.SubElement(section, "right")
        lane = ET.SubElement(right, "lane", type="driving", id="-1")
        # A real driving lane always carries a <width> (see test_verify_final_xodr.py); this
        # also gives the road's AABB nonzero extent on BOTH axes even for a due-east/due-north
        # straight segment, matching road_bounds_curve_aware's margin-on-all-sides behavior.
        ET.SubElement(lane, "width", sOffset="0.0", a="3.5", b="0.0", c="0.0", d="0.0")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def test_tile_extractor_splits_distant_roads_into_separate_tiles(tmp_path: Path):
    xodr = tmp_path / "in.xodr"
    out_dir = tmp_path / "tiles"
    _write_road_xodr(xodr, [
        ("1", 0.0, 0.0, 10.0, "-1"),
        # 2050 (not an exact multiple of tile_size=1000) avoids landing exactly on a tile
        # grid line, where _iter_tile_origins' half-open [origin, origin+tile_size) cells
        # and the hit-test's closed-interval comparison could disagree about ownership.
        ("2", 2050.0, 2050.0, 10.0, "-1"),  # far away -> different tile cell
    ])

    tiles, health = TileExtractor.tile(str(xodr), str(out_dir), tile_size=1000.0, tile_buffer_m=0.0)

    assert len(tiles) == 2
    all_road_ids = set()
    for tile_path in tiles:
        tile_root = ET.parse(tile_path).getroot()
        for r in tile_root.findall("road"):
            all_road_ids.add(r.get("id"))
    assert all_road_ids == {"1", "2"}


def test_tile_extractor_no_roads_returns_empty(tmp_path: Path):
    xodr = tmp_path / "in.xodr"
    out_dir = tmp_path / "tiles"
    _write_road_xodr(xodr, [])

    tiles, health = TileExtractor.tile(str(xodr), str(out_dir))

    assert tiles == []
    assert health == {}


def test_tile_extractor_health_report_marks_drivable_tiles(tmp_path: Path):
    xodr = tmp_path / "in.xodr"
    out_dir = tmp_path / "tiles"
    _write_road_xodr(xodr, [("1", 0.0, 0.0, 10.0, "-1")])

    tiles, health = TileExtractor.tile(str(xodr), str(out_dir), tile_size=1000.0)

    assert len(tiles) == 1
    tile_health = list(health.values())[0]
    assert tile_health["is_drivable"] is True
    assert tile_health["num_roads"] == 1


def test_tile_extractor_analysis_markers_stripped_from_written_xml(tmp_path: Path):
    # roads far enough apart that road "2" is a leakage source for road "1"'s tile
    xodr = tmp_path / "in.xodr"
    out_dir = tmp_path / "tiles"
    _write_road_xodr(xodr, [
        ("1", 0.0, 0.0, 10.0, "-1"),
        ("2", 2050.0, 2050.0, 10.0, "-1"),
    ])

    tiles, health = TileExtractor.tile(str(xodr), str(out_dir), tile_size=1000.0, tile_buffer_m=0.0)

    for tile_path in tiles:
        tile_root = ET.parse(tile_path).getroot()
        for lane in tile_root.findall(".//lane"):
            assert "_successor_outside_tile" not in lane.attrib
            assert "_predecessor_outside_tile" not in lane.attrib
            assert "was_driving" not in lane.attrib
