# -*- coding: utf-8 -*-
"""Tests for RoadClassificationGap (ultimate_pipeline/quality/road_classification_gap.py).

Live: imported and called by run_full_domain_gap.py
(RoadClassificationGap.compute() -> whole_class_gap, one of the RQ1
domain-gap metrics). Zero prior test coverage. Note: there is a DIFFERENT,
confirmed-dead ultimate_pipeline/domain_gap/road_classification_gap.py with
the same class name and purpose but zero importers -- this file is the live
one.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.road_classification_gap import RoadClassificationGap


def _road(rid, rtype=None, user_data_class=None):
    road = ET.Element("road", id=rid, length="10")
    if rtype is not None:
        ET.SubElement(road, "type", s="0", type=rtype)
    if user_data_class is not None:
        ud = ET.SubElement(road, "userData")
        ET.SubElement(ud, "param", name="road_class", value=user_data_class)
    return road


def _write(tmp_path: Path, name: str, roads) -> str:
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    p = tmp_path / name
    ET.ElementTree(root).write(str(p))
    return str(p)


def test_native_type_attribute_extracted_from_file(tmp_path):
    path = _write(tmp_path, "m.xodr", [
        _road("1", rtype="motorway"),
        _road("2", rtype="town"),
        _road("3", rtype="motorway"),
    ])
    counts = RoadClassificationGap._extract_classes(path)
    assert counts == {"motorway": 2, "town": 1}


def test_userdata_fallback_used_when_no_native_type(tmp_path):
    path = _write(tmp_path, "m.xodr", [_road("1", user_data_class="residential")])
    counts = RoadClassificationGap._extract_classes(path)
    assert counts == {"residential": 1}


def test_native_type_takes_precedence_over_userdata(tmp_path):
    path = _write(tmp_path, "m.xodr", [
        _road("1", rtype="motorway", user_data_class="residential"),
    ])
    counts = RoadClassificationGap._extract_classes(path)
    assert counts == {"motorway": 1}


def test_road_with_neither_source_classified_as_unknown(tmp_path):
    path = _write(tmp_path, "m.xodr", [_road("1")])
    counts = RoadClassificationGap._extract_classes(path)
    assert counts == {"unknown": 1}


def test_compute_reports_per_class_delta(tmp_path):
    manual = _write(tmp_path, "manual.xodr", [
        _road("1", rtype="motorway"),
        _road("2", rtype="motorway"),
        _road("3", rtype="town"),
    ])
    auto = _write(tmp_path, "auto.xodr", [
        _road("1", rtype="motorway"),
        _road("2", rtype="town"),
        _road("3", rtype="town"),
    ])
    gap = RoadClassificationGap.compute(manual, auto)
    assert gap["manual_counts"] == {"motorway": 2, "town": 1}
    assert gap["auto_counts"] == {"motorway": 1, "town": 2}
    assert gap["per_class_diff"]["motorway"]["delta"] == -1
    assert gap["per_class_diff"]["town"]["delta"] == 1
