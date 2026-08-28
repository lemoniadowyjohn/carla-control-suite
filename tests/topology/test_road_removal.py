"""Tests for ultimate_pipeline/topology/road_removal.py.

Zero prior test coverage. RoadRemoval.remove() is a deliberate no-op
("SAFE MODE" per its own module docstring: "preserves all roads"). It is
NOT called anywhere in ultimate_pipeline/ (confirmed via grep) -- unlike
missing_junction_link_repair, semantic_verifier, and structure_scanner,
which are all wired into stage_02_topology_semantics.py, this class has no
current caller. These tests lock down the documented no-op contract so
that if a future caller relies on it doing something, that expectation
surfaces as a test failure rather than a silent behavior mismatch.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.road_removal import RoadRemoval


def _root(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{xml_body}\n</OpenDRIVE>')


def test_remove_returns_zero():
    root = _root('<road id="1"/><road id="2"/>')
    result = RoadRemoval.remove(root, ["1"])
    assert result == 0


def test_remove_does_not_delete_any_road():
    root = _root('<road id="1"/><road id="2"/>')
    before = ET.tostring(root)
    RoadRemoval.remove(root, ["1", "2"])
    after = ET.tostring(root)
    assert before == after
    assert len(root.findall("road")) == 2


def test_remove_with_empty_road_id_list_still_preserves_roads():
    root = _root('<road id="1"/>')
    result = RoadRemoval.remove(root, [])
    assert result == 0
    assert len(root.findall("road")) == 1


def test_remove_does_not_raise_on_unknown_ids():
    root = _root('<road id="1"/>')
    # road_ids referencing non-existent roads must not raise.
    result = RoadRemoval.remove(root, ["does-not-exist"])
    assert result == 0
