# ultimate_pipeline/tests/unit/test_osm_meta_index.py
"""
Unit tests for ultimate_pipeline.enrichment.osm_meta_index.

Tests the lightweight OSM XML parser that feeds speed_limit_writer,
turn_lanes_writer, and regulatory_sign_writer in stage_04_enrichment.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index
from ultimate_pipeline.enrichment.speed_limit_writer import apply_speed_limits, parse_maxspeed
from ultimate_pipeline.enrichment.turn_lanes_writer import apply_turn_lanes
from ultimate_pipeline.enrichment.regulatory_sign_writer import apply_regulatory_signs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_osm(content: str) -> str:
    """Write content to a temp .osm file and return the path."""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".osm", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        return f.name


def _minimal_osm(*ways: dict) -> str:
    """Build a minimal OSM XML string from a list of way dicts."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6">']
    for way in ways:
        wid = way["id"]
        lines.append(f'  <way id="{wid}">')
        for k, v in way.get("tags", {}).items():
            lines.append(f'    <tag k="{k}" v="{v}"/>')
        lines.append("  </way>")
    lines.append("</osm>")
    return "\n".join(lines)


def _xodr_with_roads(*roads) -> ET.Element:
    """Build a minimal XODR root element with driving lanes.

    Each entry in *roads* is either a bare id string (road gets no `name`
    attribute) or an (id, name) tuple -- osm_meta_index keys by street NAME,
    not XODR road id (see osm_meta_index.py docstring: the two are disjoint
    numbering schemes, verified 2026-08-26), so writer-integration tests must
    set a matching `name` attribute to exercise a real match.
    """
    root = ET.Element("OpenDRIVE")
    for entry in roads:
        rid, name = entry if isinstance(entry, tuple) else (entry, None)
        attrs = {"id": rid}
        if name:
            attrs["name"] = name
        road = ET.SubElement(root, "road", attrs)
        lanes = ET.SubElement(road, "lanes")
        ls = ET.SubElement(lanes, "laneSection")
        right = ET.SubElement(ls, "right")
        ET.SubElement(right, "lane", id="-1", type="driving")
    return root


# ---------------------------------------------------------------------------
# osm_meta_index unit tests
# ---------------------------------------------------------------------------

class TestBuildOsmMetaIndex:
    def test_extracts_maxspeed(self):
        path = _write_osm(_minimal_osm(
            {"id": "100", "tags": {"name": "Hauptstraße", "highway": "secondary", "maxspeed": "50"}}
        ))
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert "Hauptstraße" in idx
        assert idx["Hauptstraße"]["maxspeed"] == "50"

    def test_extracts_turn_lanes_colon_variant(self):
        path = _write_osm(_minimal_osm(
            {"id": "200", "tags": {"name": "Industriestraße", "highway": "primary", "turn:lanes": "left|straight|right"}}
        ))
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert "Industriestraße" in idx
        assert idx["Industriestraße"]["turn_lanes"] == "left|straight|right"

    def test_extracts_turn_lanes_underscore_variant(self):
        path = _write_osm(_minimal_osm(
            {"id": "201", "tags": {"name": "Schulstraße", "turn_lanes": "through|right"}}
        ))
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert idx["Schulstraße"]["turn_lanes"] == "through|right"

    def test_extracts_traffic_sign(self):
        path = _write_osm(_minimal_osm(
            {"id": "300", "tags": {"name": "Kirchgasse", "traffic_sign": "de:206"}}
        ))
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert idx["Kirchgasse"]["traffic_sign"] == "de:206"

    def test_omits_ways_without_enrichment_tags(self):
        path = _write_osm(_minimal_osm(
            {"id": "999", "tags": {"highway": "footway", "name": "Fußweg"}}
        ))
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert "999" not in idx

    def test_handles_missing_file_gracefully(self):
        idx = build_osm_meta_index("/nonexistent/does_not_exist.osm")
        assert idx == {}

    def test_handles_malformed_xml_gracefully(self):
        path = _write_osm("<osm><way id='1'><UNCLOSED")
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert isinstance(idx, dict)  # must not raise

    def test_multiple_ways(self):
        path = _write_osm(_minimal_osm(
            {"id": "1", "tags": {"name": "Erste Straße", "maxspeed": "30"}},
            {"id": "2", "tags": {"name": "Zweite Straße", "turn:lanes": "left|right"}},
            {"id": "3", "tags": {"name": "Dritte Straße", "traffic_sign": "de:205"}},
            {"id": "4", "tags": {"name": "Hauptstraße"}},  # no enrichment tag
        ))
        try:
            idx = build_osm_meta_index(path)
        finally:
            os.unlink(path)
        assert len(idx) == 3
        assert "Hauptstraße" not in idx


# ---------------------------------------------------------------------------
# parse_maxspeed unit tests
# ---------------------------------------------------------------------------

class TestParseMaxspeed:
    @pytest.mark.parametrize("raw,expected", [
        ("50", 50),
        ("30 mph", 48),
        ("de:urban", 50),
        ("DE:motorway", 130),
        ("de:living_street", 7),
        ("none", None),
        ("walk", 7),
        (None, None),
        ("", None),
        ("unparseable_garbage", None),
    ])
    def test_known_values(self, raw, expected):
        assert parse_maxspeed(raw) == expected


# ---------------------------------------------------------------------------
# Integration: index → writers
# ---------------------------------------------------------------------------

class TestWriterIntegration:
    def _index_from_ways(self, *ways):
        path = _write_osm(_minimal_osm(*ways))
        try:
            return build_osm_meta_index(path)
        finally:
            os.unlink(path)

    def test_speed_limit_applied_to_matching_road(self):
        idx = self._index_from_ways({"id": "7765", "tags": {"name": "Teststraße", "maxspeed": "50"}})
        root = _xodr_with_roads(("7765", "Teststraße"))
        n = apply_speed_limits(root, idx)
        assert n == 1
        speed_elem = root.find(".//lane/speed")
        assert speed_elem is not None
        assert speed_elem.get("max") == "50"
        assert speed_elem.get("unit") == "km/h"

    def test_speed_limit_skipped_for_unmatched_road(self):
        idx = self._index_from_ways({"id": "9999", "tags": {"maxspeed": "80"}})
        root = _xodr_with_roads("1111")  # different road
        n = apply_speed_limits(root, idx)
        assert n == 0

    def test_turn_lane_marking_inserted(self):
        idx = self._index_from_ways({"id": "500", "tags": {"name": "Bahnhofstraße", "turn:lanes": "left|straight"}})
        root = _xodr_with_roads(("500", "Bahnhofstraße"))
        n = apply_turn_lanes(root, idx)
        assert n == 1
        ud = root.find(".//road/userData")
        assert ud is not None
        vec = ud.find("vector[@key='turnMarking']")
        assert vec is not None
        assert vec.get("value") == "left|straight"

    def test_regulatory_sign_inserted(self):
        idx = self._index_from_ways({"id": "600", "tags": {"name": "Münchener Straße", "traffic_sign": "de:206"}})
        root = _xodr_with_roads(("600", "Münchener Straße"))
        n = apply_regulatory_signs(root, idx)
        assert n == 1
        obj = root.find(".//road/objects/object")
        assert obj is not None
        assert obj.get("type") == "stop"
        assert obj.get("name") == "de:206"

    def test_all_writers_noop_on_empty_index(self):
        root = _xodr_with_roads("100", "200")
        assert apply_speed_limits(root, {}) == 0
        assert apply_turn_lanes(root, {}) == 0
        assert apply_regulatory_signs(root, {}) == 0

    def test_duplicate_speed_not_inserted_twice(self):
        idx = self._index_from_ways({"id": "42", "tags": {"name": "Ringstraße", "maxspeed": "70"}})
        root = _xodr_with_roads(("42", "Ringstraße"))
        n1 = apply_speed_limits(root, idx)
        assert n1 == 1  # sanity: the first call actually matched and inserted
        n2 = apply_speed_limits(root, idx)  # second call
        assert n2 == 0  # lane already has <speed>
