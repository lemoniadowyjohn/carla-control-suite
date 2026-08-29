# -*- coding: utf-8 -*-
"""Tests for SemanticGap (ultimate_pipeline/domain_gap/semantic_gap.py).

Live: imported by run_full_domain_gap.py -- feeds the RQ1 semantic domain-gap
metric (object counts, road-type length distribution, traffic-light and
lane-marking density). Zero prior test coverage.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap


def _road(rid, length, rtype="town", objects=(), lane_marks=0):
    road = ET.Element("road", id=rid, length=f"{length}")
    if rtype is not None:
        ET.SubElement(road, "type", s="0", type=rtype)
    if objects:
        objs = ET.SubElement(road, "objects")
        for i, otype in enumerate(objects):
            ET.SubElement(objs, "object", id=str(i), type=otype)
    if lane_marks:
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0")
        lane = ET.SubElement(ET.SubElement(section, "left"), "lane", id="1")
        for _ in range(lane_marks):
            ET.SubElement(lane, "laneMark")
    return road


def _write(tmp_path: Path, name: str, roads) -> str:
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    p = tmp_path / name
    ET.ElementTree(root).write(str(p))
    return str(p)


def test_traffic_light_objects_counted():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", 10, objects=["traffic_light", "crosswalk", "traffic_light"]))
    assert SemanticGap._count_traffic_lights(root) == 2


def test_object_counts_by_type():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", 10, objects=["crosswalk", "crosswalk", "building"]))
    counts = SemanticGap._count_objects_by_type(root)
    assert counts == {"crosswalk": 2, "building": 1}


def test_road_type_lengths_grouped():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", 100, rtype="motorway"))
    root.append(_road("2", 50, rtype="motorway"))
    root.append(_road("3", 30, rtype="town"))
    lengths = SemanticGap._road_type_lengths(root)
    assert lengths == {"motorway": 150.0, "town": 30.0}


def test_lane_markings_counted():
    root = ET.Element("OpenDRIVE")
    root.append(_road("1", 10, lane_marks=3))
    assert SemanticGap._count_lane_markings(root) == 3


def test_compare_reports_deltas(tmp_path):
    manual = _write(
        tmp_path, "manual.xodr",
        [_road("1", 100, rtype="motorway", objects=["traffic_light"], lane_marks=2)],
    )
    auto = _write(
        tmp_path, "auto.xodr",
        [_road("1", 100, rtype="motorway", objects=["traffic_light", "traffic_light"], lane_marks=4)],
    )
    gap = SemanticGap.compare(manual, auto)
    assert gap["objects"]["delta"]["traffic_light"] == 1
    assert gap["traffic_lights"]["manual_count"] == 1
    assert gap["traffic_lights"]["auto_count"] == 2
    assert gap["lane_markings"]["delta_density"] > 0
    assert gap["meta"]["normalized"] is True


def test_compute_is_alias_for_compare(tmp_path):
    manual = _write(tmp_path, "manual.xodr", [_road("1", 10)])
    auto = _write(tmp_path, "auto.xodr", [_road("1", 10)])
    assert SemanticGap.compute(manual, auto) == SemanticGap.compare(manual, auto)
