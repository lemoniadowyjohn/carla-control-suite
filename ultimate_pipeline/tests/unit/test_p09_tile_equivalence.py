# -*- coding: utf-8 -*-
"""P09 TIL-EQV-001 tests: curve-aware bounds, ownership, duplication equivalence."""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.tiling.tile_equivalence import (
    assert_duplicated_roads_identical,
    road_bounds_curve_aware,
    road_max_lane_half_width,
    tile_road_ownership,
    verify_tile_adjacency,
)


def _line_geom(x, y, hdg, length, s=0.0):
    g = ET.Element("geometry", s=f"{s:.3f}", x=f"{x:.3f}", y=f"{y:.3f}",
                   hdg=f"{hdg:.6f}", length=f"{length:.3f}")
    ET.SubElement(g, "line")
    return g


def _arc_geom(x, y, hdg, length, curvature, s=0.0):
    g = ET.Element("geometry", s=f"{s:.3f}", x=f"{x:.3f}", y=f"{y:.3f}",
                   hdg=f"{hdg:.6f}", length=f"{length:.3f}")
    ET.SubElement(g, "arc", curvature=f"{curvature:.6f}")
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
        assert b["x_min"] == pytest.approx(0.0)
        assert b["x_max"] == pytest.approx(100.0)
        assert b["y_min"] == pytest.approx(0.0)
        assert b["y_max"] == pytest.approx(0.0)

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


class TestOwnership:
    def test_midpoint_policy(self):
        road = _road("1", [_line_geom(0, 0, 0.0, 100.0)])
        tiles = {"t0": (0.0, 0.0, 50.0, 50.0), "t1": (50.0, 0.0, 100.0, 50.0)}
        res = tile_road_ownership(_root([road]), tiles, policy="midpoint")
        assert res["ownership"]["1"] == "t1"
        assert res["assigned"] == 1

    def test_junction_context_kept_together(self):
        r1 = _road("1", [_line_geom(0, 0, 0.0, 20.0)], junction="j1")
        r2 = _road("2", [_line_geom(10, 0, 0.0, 20.0)], junction="j1")
        tiles = {"t0": (0.0, 0.0, 15.0, 15.0), "t1": (15.0, 0.0, 30.0, 15.0)}
        res = tile_road_ownership(_root([r1, r2]), tiles, policy="midpoint")
        assert res["ownership"]["1"] == res["ownership"]["2"]

    def test_invalid_policy(self):
        with pytest.raises(ValueError):
            tile_road_ownership(_root([]), {}, policy="center")


class TestDuplicates:
    def test_identical_copies_pass(self, tmp_path):
        geom = _line_geom(0, 0, 0.0, 100.0)
        road = _road("7", [geom])
        root1, root2 = _root([road]), _root([road])
        _write_tile(str(tmp_path), "a.xodr", root1)
        _write_tile(str(tmp_path), "b.xodr", root2)
        res = assert_duplicated_roads_identical(str(tmp_path))
        assert res["ok"] is True
        assert res["duplicated_road_count"] == 1
        assert res["roads"][0]["byte_identical"] is True
        assert res["roads"][0]["semantic_identical"] is True

    def test_divergent_copies_violate(self, tmp_path):
        road_a = _road("7", [_line_geom(0, 0, 0.0, 100.0)])
        road_b = _road("7", [_line_geom(0, 0, 0.0, 100.0)])
        w = road_b.find("./lanes/laneSection/left/lane/width")
        w.set("a", "9.9")
        _write_tile(str(tmp_path), "a.xodr", _root([road_a]))
        _write_tile(str(tmp_path), "b.xodr", _root([road_b]))
        res = assert_duplicated_roads_identical(str(tmp_path))
        assert res["ok"] is False
        assert res["violation_count"] == 1
        assert res["roads"][0]["byte_identical"] is False


class TestAdjacency:
    def test_touching_tiles_adjacent(self):
        tiles = {"t0": (0.0, 0.0, 10.0, 10.0), "t1": (10.0, 0.0, 20.0, 10.0)}
        res = verify_tile_adjacency(tiles, {"t0": ["t1"], "t1": ["t0"]})
        assert res["ok"] is True

    def test_missing_connection_reported(self):
        tiles = {"t0": (0.0, 0.0, 10.0, 10.0), "t1": (10.0, 0.0, 20.0, 10.0)}
        res = verify_tile_adjacency(tiles, {"t0": [], "t1": []})
        assert res["ok"] is False
        assert res["missing_connections"] == ["t0", "t1"]
