#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tile equivalence (TIL-001/002/004 curve-aware bounds and ownership).

This module tests the curve-aware bounds computation and road ownership logic
that powers the tiling system's tile assignment and deduplication logic.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.tile_equivalence import (
    road_bounds_curve_aware,
    road_max_lane_half_width,
    tile_road_ownership,
    assert_duplicated_roads_identical,
    verify_tile_adjacency,
)


def _safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _line_geom(x, y, hdg, length):
    g = ET.Element("geometry", s="0", x=str(x), y=str(y), hdg=str(hdg), length=str(length))
    ET.SubElement(g, "line")
    return g


def _arc_geom(x, y, hdg, length, curvature):
    g = ET.Element("geometry", s="0", x=str(x), y=str(y), hdg=str(hdg), length=str(length))
    ET.SubElement(g, "arc", curvature=str(curvature))
    return g


def _road(rid, geoms, junction=None, width=3.5):
    road = ET.Element("road", id=rid, length=f"{sum(float(g.get('length')) for g in geoms):.3f}")
    if junction:
        road.set("junction", junction)
    pv = ET.SubElement(road, "planView")
    for g in geoms:
        pv.append(g)
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0.0")
    ET.SubElement(section, "center").append(ET.Element("lane", id="0"))
    for side in ("left", "right"):
        lane = ET.SubElement(ET.SubElement(section, side), "lane", id=str(side == "left"))
        ET.SubElement(lane, "width", sOffset="0", a=f"{width:.3f}")
    return road


def _root(roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


def _write_tile(dirpath, fname, root):
    os.makedirs(dirpath, exist_ok=True)
    ET.ElementTree(root).write(os.path.join(dirpath, fname), encoding="utf-8", xml_declaration=True)


class TestCurveAwareBounds:
    def test_line_bounds_matched(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 100.0)])
        b = road_bounds_curve_aware(road, margin_m=0.0, include_lane_width=False)
        assert b["x_min"] == pytest.approx(0.0, abs=1e-3)
        assert b["x_max"] == pytest.approx(100.0, abs=1e-3)
        assert b["y_min"] == pytest.approx(0.0, abs=1e-3)
        assert b["y_max"] == pytest.approx(0.0, abs=1e-3)

    def test_half_circle_arc_extent(self):
        # half circle of radius 10: start (0,0) hdg 0, length pi*10 -> center (0,10)
        r = 10.0
        length = math.pi * r
        road = _road("1", [_arc_geom(0, 0, 0.0, length, 1.0 / r)])
        b = road_bounds_curve_aware(road, margin_m=0.0, include_lane_width=False)
        assert b["x_min"] == pytest.approx(0.0, abs=1e-3)
        assert b["x_max"] == pytest.approx(10.0, abs=1e-3)
        assert b["y_min"] == pytest.approx(0.0, abs=1e-3)
        assert b["y_max"] == pytest.approx(20.0, abs=1e-3)

    def test_lane_width_inflates_bounds(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 50.0)], width=3.5)
        b = road_bounds_curve_aware(road, margin_m=0.0, include_lane_width=True)
        assert b["margin_m"] == pytest.approx(3.5)
        assert b["y_min"] == pytest.approx(-3.5)
        assert b["y_max"] == pytest.approx(3.5)

    def test_max_half_width_across_sections(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 50.0)], width=3.5)
        assert road_max_lane_half_width(road) == pytest.approx(3.5)

    def test_nonfinite_width_not_silently_dropped(self):
        # max(half, abs(_safe_float(...))) silently drops a NaN candidate:
        # Python's max(a, b) keeps `a` when `b > a` is False, and `nan > 0.0`
        # is always False in IEEE-754. A corrupted width coefficient must not
        # be treated as narrower than a real one -- TIL-001 requires the tile
        # margin to be inflated enough that "no lane escapes the tile".
        road = _road("1", [_line_geom(0, 0, 0.0, 50.0)], width=3.5)
        lanes = road.find("lanes")
        section = lanes.find("laneSection")
        left_lane = section.find("left/lane")
        ET.SubElement(left_lane, "width", sOffset="10", a="nan")
        assert not math.isfinite(road_max_lane_half_width(road))


class TestOwnership:
    def test_midpoint_policy(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 100.0)])
        tiles = {
            "tile_0_0": (0.0, 0.0, 50.0, 50.0),
            "tile_0_1": (50.0, 0.0, 100.0, 50.0),
        }
        res = tile_road_ownership(_root([road]), tiles, policy="midpoint")
        assert res["ownership"]["1"] == "tile_0_1"

    def test_start_policy(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 100.0)])
        tiles = {
            "tile_0_0": (0.0, 0.0, 50.0, 50.0),
            "tile_0_1": (50.0, 0.0, 100.0, 50.0),
        }
        res = tile_road_ownership(_root([road]), tiles, policy="start")
        assert res["ownership"]["1"] == "tile_0_0"

    def test_junction_context_kept_together(self):
        road_a = _road("1", [_line_geom(0, 0, 0.0, 50.0)], junction="42")
        road_b = _road("2", [_line_geom(50, 0, 0.0, 50.0)], junction="42")
        road_c = _road("3", [_line_geom(100, 0, 0.0, 50.0)])
        tiles = {
            "tile_0_0": (0.0, 0.0, 60.0, 60.0),
            "tile_0_1": (60.0, 0.0, 120.0, 60.0),
        }
        root = _root([road_a, road_b, road_c])
        res = tile_road_ownership(root, tiles, policy="midpoint")
        # Both junction roads should be assigned to the same tile
        assert res["ownership"]["1"] == res["ownership"]["2"]

    def test_invalid_policy(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 10.0)])
        tiles = {"tile_0_0": (0.0, 0.0, 10.0, 10.0)}
        with pytest.raises(ValueError, match="policy must be 'midpoint' or 'start'"):
            tile_road_ownership(_root([road]), tiles, policy="invalid")


class TestDuplicates:
    def test_identical_copies_pass(self):
        tile_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "tests", "unit", "test_data", "tiles")
        # Skip if test data not available
        if not os.path.exists(tile_dir):
            pytest.skip("test tile data not available")
        res = assert_duplicated_roads_identical(tile_dir)
        assert res["ok"] is True

    def test_divergent_copies_violate(self):
        # This test would require a fixture with divergent roads; skip for now
        pass


class TestAdjacency:
    def test_touching_tiles_adjacent(self):
        tiles = {
            "tile_0_0": (0.0, 0.0, 10.0, 10.0),
            "tile_0_1": (10.0, 0.0, 20.0, 10.0),
        }
        border_connections = {"tile_0_0": ["tile_0_1"], "tile_0_1": ["tile_0_0"]}
        res = verify_tile_adjacency(tiles, border_connections)
        assert res["ok"] is True

    def test_missing_connection_reported(self):
        tiles = {
            "tile_0_0": (0.0, 0.0, 10.0, 10.0),
            "tile_0_1": (10.0, 0.0, 20.0, 10.0),
        }
        border_connections = {"tile_0_0": [], "tile_0_1": []}
        res = verify_tile_adjacency(tiles, border_connections)
        assert res["ok"] is False
        assert "missing_connections" in res


if __name__ == "__main__":
    pytest.main([__file__, "-v"])