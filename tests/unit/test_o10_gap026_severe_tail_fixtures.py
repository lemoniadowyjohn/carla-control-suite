"""Tests for O10 reduced GAP-026 fixtures."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder


FIXTURES = [
    "gap026_0_25_0_5", "gap026_1_3", "gap026_3_5", "gap026_5_10", "gap026_over_10"
]


def test_all_fixtures_reproduce_failure():
    for fixture in FIXTURES:
        path = Path("tests/data/gap026_fixtures") / f"{fixture}.xodr"
        assert path.is_file(), path
        result = LaneLinkBuilder.sanitize_junction_lane_links(ET.parse(path).getroot(), label=fixture)
        assert result["summary_metrics"]["checked"] == 1
        assert result["summary_metrics"]["failed"] == 1


def test_fixture_contains_only_required_roads():
    path = Path("tests/data/gap026_fixtures/gap026_3_5.xodr")
    root = ET.parse(path).getroot()
    assert {r.get("id") for r in root.findall("road")} == {"42486", "52027"}
    assert len(root.findall("junction")) == 1
    assert len(root.findall("junction/connection/laneLink")) == 1
