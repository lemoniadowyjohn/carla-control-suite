# -*- coding: utf-8 -*-
"""Tests for building multipolygon fidelity (OC-49)."""
from __future__ import annotations

import tempfile
import json
import os

import pytest

from ultimate_pipeline.tiling.tile_fbx_generator import (
    load_buildings_from_overpass_json,
    write_tile_osm_xml,
    BuildingPolygon,
    TileBuilding,
    compute_building_statistics,
)


def test_simple_way_building_preserved():
    """A simple way building should be emitted as a standalone way."""
    data = {
        "elements": [{
            "type": "way",
            "id": 1,
            "tags": {"building": "yes"},
            "geometry": [
                {"lon": 10.0, "lat": 50.0},
                {"lon": 10.001, "lat": 50.0},
                {"lon": 10.001, "lat": 50.001},
                {"lon": 10.0, "lat": 50.001},
                {"lon": 10.0, "lat": 50.0}
            ]
        }]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        buildings = load_buildings_from_overpass_json(fname)
        assert len(buildings) == 1
        b = buildings[0]
        assert b.source_type == "way"
        assert len(b.parts) == 1
        assert not b.parts[0].inners
        assert b.relation_diagnostics is None
    finally:
        os.unlink(fname)


def test_relation_with_courtyard_preserves_inner_ring():
    """A multipolygon relation with an inner ring should preserve the hole."""
    data = {
        "elements": [{
            "type": "relation",
            "id": 2,
            "tags": {"building": "yes", "type": "multipolygon"},
            "members": [
                {
                    "type": "way", "role": "outer", "ref": 100,
                    "geometry": [
                        {"lon": 10.1, "lat": 50.1},
                        {"lon": 10.102, "lat": 50.1},
                        {"lon": 10.102, "lat": 50.102},
                        {"lon": 10.1, "lat": 50.102},
                        {"lon": 10.1, "lat": 50.1}
                    ]
                },
                {
                    "type": "way", "role": "inner", "ref": 101,
                    "geometry": [
                        {"lon": 10.1005, "lat": 50.1005},
                        {"lon": 10.1015, "lat": 50.1005},
                        {"lon": 10.1015, "lat": 50.1015},
                        {"lon": 10.1005, "lat": 50.1015},
                        {"lon": 10.1005, "lat": 50.1005}
                    ]
                }
            ]
        }]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        buildings = load_buildings_from_overpass_json(fname)
        assert len(buildings) == 1
        b = buildings[0]
        assert b.source_type == "relation"
        assert len(b.parts) == 1
        assert len(b.parts[0].inners) == 1
        assert b.relation_diagnostics is not None
        assert b.relation_diagnostics["inner_rings_built"] == 1
        assert b.relation_diagnostics["status"] == "ok"
    finally:
        os.unlink(fname)


def test_multipart_relation_preserves_multiple_outers():
    """A multipolygon with multiple outer rings should create multiple parts."""
    data = {
        "elements": [{
            "type": "relation",
            "id": 3,
            "tags": {"building": "yes", "type": "multipolygon"},
            "members": [
                {
                    "type": "way", "role": "outer", "ref": 200,
                    "geometry": [
                        {"lon": 10.2, "lat": 50.2},
                        {"lon": 10.201, "lat": 50.2},
                        {"lon": 10.201, "lat": 50.201},
                        {"lon": 10.2, "lat": 50.201},
                        {"lon": 10.2, "lat": 50.2}
                    ]
                },
                {
                    "type": "way", "role": "outer", "ref": 201,
                    "geometry": [
                        {"lon": 10.21, "lat": 50.21},
                        {"lon": 10.211, "lat": 50.21},
                        {"lon": 10.211, "lat": 50.211},
                        {"lon": 10.21, "lat": 50.211},
                        {"lon": 10.21, "lat": 50.21}
                    ]
                }
            ]
        }]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        buildings = load_buildings_from_overpass_json(fname)
        assert len(buildings) == 1
        b = buildings[0]
        assert b.source_type == "relation"
        assert len(b.parts) == 2
        assert b.relation_diagnostics is not None
        assert b.relation_diagnostics["outer_rings_built"] == 2
    finally:
        os.unlink(fname)


def test_write_tile_osm_xml_emits_multipolygon_relation():
    """A building with inner rings should be emitted as a multipolygon relation."""
    building = TileBuilding(
        source_id="test_1",
        source_type="relation",
        tags={"building": "yes"},
        parts=[
            BuildingPolygon(
                outer=[(10.0, 50.0), (10.001, 50.0), (10.001, 50.001), (10.0, 50.001), (10.0, 50.0)],
                inners=(
                    [(10.0002, 50.0002), (10.0008, 50.0002), (10.0008, 50.0008), (10.0002, 50.0008), (10.0002, 50.0002)],
                ),
            )
        ],
        relation_diagnostics={"status": "ok"}
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test.osm")
        result = write_tile_osm_xml([building], out_path)
        assert result["relations_written"] == 1
        assert result["ways_written"] == 2  # outer + inner

        # Parse and verify structure
        import xml.etree.ElementTree as ET
        tree = ET.parse(out_path)
        root = tree.getroot()

        # Should have one relation
        relations = root.findall("relation")
        assert len(relations) == 1
        rel = relations[0]
        assert rel.get("id") is not None
        assert rel.find("tag[@k='type'][@v='multipolygon']") is not None

        # Relation should have 2 members: 1 outer, 1 inner
        members = rel.findall("member")
        assert len(members) == 2
        roles = sorted([m.get("role") for m in members])
        assert roles == ["inner", "outer"]


def test_write_tile_osm_xml_simple_building_emits_way():
    """A simple building without holes should be emitted as a standalone way."""
    building = TileBuilding(
        source_id="test_1",
        source_type="way",
        tags={"building": "yes"},
        parts=[
            BuildingPolygon(
                outer=[(10.0, 50.0), (10.001, 50.0), (10.001, 50.001), (10.0, 50.001), (10.0, 50.0)],
                inners=(),
            )
        ],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test.osm")
        result = write_tile_osm_xml([building], out_path)
        assert result["relations_written"] == 0
        assert result["ways_written"] == 1

        import xml.etree.ElementTree as ET
        tree = ET.parse(out_path)
        root = tree.getroot()

        # Should have one way with building tag
        ways = root.findall("way")
        assert len(ways) == 1
        way = ways[0]
        assert way.find("tag[@k='building'][@v='yes']") is not None


def test_compute_building_statistics_reports_courtyard_area():
    """compute_building_statistics should report courtyard area preserved."""
    building = TileBuilding(
        source_id="test_1",
        source_type="relation",
        tags={"building": "yes"},
        parts=[
            BuildingPolygon(
                outer=[(10.0, 50.0), (10.001, 50.0), (10.001, 50.001), (10.0, 50.001), (10.0, 50.0)],
                inners=(
                    [(10.0002, 50.0002), (10.0008, 50.0002), (10.0008, 50.0008), (10.0002, 50.0008), (10.0002, 50.0002)],
                ),
            )
        ],
    )
    stats = compute_building_statistics([building])
    assert stats["building_count"] == 1
    assert stats["relation_count"] == 1
    assert stats["relations_with_holes"] == 1
    assert stats["inner_ring_count"] == 1
    assert stats["total_hole_area_m2"] > 0
    assert stats["courtyard_area_preserved_m2"] > 0
    assert stats["courtyard_area_preserved_m2"] == stats["total_hole_area_m2"]


def test_relation_diagnostics_report_ambiguous_inners():
    """Inner rings not associated with any outer should be flagged."""
    data = {
        "elements": [{
            "type": "relation",
            "id": 4,
            "tags": {"building": "yes", "type": "multipolygon"},
            "members": [
                {
                    "type": "way", "role": "outer", "ref": 300,
                    "geometry": [
                        {"lon": 10.3, "lat": 50.3},
                        {"lon": 10.301, "lat": 50.3},
                        {"lon": 10.301, "lat": 50.301},
                        {"lon": 10.3, "lat": 50.301},
                        {"lon": 10.3, "lat": 50.3}
                    ]
                },
                {
                    "type": "way", "role": "inner", "ref": 301,
                    "geometry": [
                        {"lon": 10.5, "lat": 50.5},  # Far outside the outer
                        {"lon": 10.501, "lat": 50.5},
                        {"lon": 10.501, "lat": 50.501},
                        {"lon": 10.5, "lat": 50.501},
                        {"lon": 10.5, "lat": 50.5}
                    ]
                }
            ]
        }]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        buildings = load_buildings_from_overpass_json(fname)
        assert len(buildings) == 1
        b = buildings[0]
        assert b.relation_diagnostics is not None
        # The inner ring is not inside the outer, so it should be flagged
        assert b.relation_diagnostics["status"] == "ambiguous_inners"
        assert len(b.relation_diagnostics["ambiguous_members"]) > 0
    finally:
        os.unlink(fname)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])