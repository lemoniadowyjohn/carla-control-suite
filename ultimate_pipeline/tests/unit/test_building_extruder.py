# -*- coding: utf-8 -*-
"""Tests for BuildingExtruder (ultimate_pipeline/enrichment/building_extruder.py).

Live: called twice by main_pipeline.py to insert <object type="building">
elements into the enriched XODR. Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.building_extruder import (
    BuildingExtruder,
    BuildingFootprint,
)


def _road_with_geometry(rid, x, y):
    road = ET.Element("road", id=rid, length="10")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x=str(x), y=str(y), hdg="0", length="10")
    return road


def _root(roads):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    return root


def test_building_assigned_to_nearest_road():
    root = _root([
        _road_with_geometry("1", 0, 0),
        _road_with_geometry("2", 1000, 1000),
    ])
    footprint = [(1, 0), (1, 1), (0, 1)]  # centroid close to road 1
    inserted = BuildingExtruder.add_buildings(
        root, [BuildingFootprint(footprint=footprint, height=12.0)]
    )
    assert inserted == 1
    obj = root.find(".//road[@id='1']/objects/object")
    assert obj is not None
    assert obj.get("type") == "building"
    assert obj.get("height") == "12.00"
    assert root.find(".//road[@id='2']/objects/object") is None


def test_degenerate_footprint_skipped():
    root = _root([_road_with_geometry("1", 0, 0)])
    # Fewer than 3 points can't form a polygon.
    inserted = BuildingExtruder.add_buildings(
        root, [BuildingFootprint(footprint=[(0, 0), (1, 1)])]
    )
    assert inserted == 0
    assert root.find(".//object") is None


def test_no_roads_means_no_insertion():
    root = _root([])
    inserted = BuildingExtruder.add_buildings(
        root, [BuildingFootprint(footprint=[(0, 0), (1, 0), (1, 1)])]
    )
    assert inserted == 0


def test_outline_corners_include_closing_point_and_preserve_order():
    root = _root([_road_with_geometry("1", 0, 0)])
    footprint = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    BuildingExtruder.add_buildings(
        root, [BuildingFootprint(footprint=footprint, height=5.0)]
    )
    corners = root.findall(".//outline/cornerGlobal")
    xy = [(float(c.get("x")), float(c.get("y"))) for c in corners]
    assert xy[:4] == footprint
    assert xy[-1] == footprint[0]  # outline is closed


def test_insert_buildings_is_alias_for_add_buildings():
    root_a = _root([_road_with_geometry("1", 0, 0)])
    root_b = _root([_road_with_geometry("1", 0, 0)])
    footprint = [(0, 0), (1, 0), (1, 1)]
    n_a = BuildingExtruder.add_buildings(root_a, [BuildingFootprint(footprint=footprint)])
    n_b = BuildingExtruder.insert_buildings(root_b, [BuildingFootprint(footprint=footprint)])
    assert n_a == n_b == 1
