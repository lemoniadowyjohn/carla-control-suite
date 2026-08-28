"""Tests for ultimate_pipeline/topology/structure_prune_legacy.py.

Zero prior test coverage. This module is opt-in only (main_pipeline.py
gates it behind settings.ENABLE_AGGRESSIVE_STRUCTURE_PRUNE, default off,
per its own docstring: "DO NOT USE FOR REAL CITY MAPS"), but it is
destructive when enabled, so its removal-selection logic is worth locking
down with tests even though it is not part of the default pipeline path.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.topology.structure_prune_legacy import (
    _legacy_scan,
    _remove_roads,
    prune,
)


def _write_xodr(tmp_path, body: str) -> str:
    path = os.path.join(str(tmp_path), "map.xodr")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{body}\n</OpenDRIVE>')
    return path


def _root(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{xml_body}\n</OpenDRIVE>')


# ---------------------------------------------------------------------------
# _legacy_scan
# ---------------------------------------------------------------------------
def test_legacy_scan_flags_multi_successor():
    root = _root(
        """
  <road id="1">
    <link>
      <successor elementType="road" elementId="2"/>
      <successor elementType="road" elementId="3"/>
    </link>
  </road>
  <road id="2"/><road id="3"/>
"""
    )
    issues = _legacy_scan(root)
    assert "1" in issues["multi_successor"]


def test_legacy_scan_flags_self_link():
    root = _root('<road id="1"><link><successor elementType="road" elementId="1"/></link></road>')
    issues = _legacy_scan(root)
    assert "1" in issues["self_links"]


def test_legacy_scan_flags_zero_geometry():
    root = _root('<road id="1"/>')
    issues = _legacy_scan(root)
    assert "1" in issues["zero_geometry"]


def test_legacy_scan_flags_broken_junction_ref():
    root = _root(
        """
  <road id="1"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="999"/></junction>
"""
    )
    issues = _legacy_scan(root)
    assert ("1", "999") in issues["broken_junction_refs"]


def test_legacy_scan_flags_endpoint_mismatch():
    root = _root(
        """
  <road id="1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView>
  </road>
  <road id="2">
    <planView><geometry s="0" x="500" y="500" hdg="0" length="10"/></planView>
  </road>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    issues = _legacy_scan(root)
    assert ("1", "2") in issues["endpoint_mismatch"]


def test_legacy_scan_clean_map_no_issues():
    root = _root(
        """
  <road id="1">
    <link><successor elementType="road" elementId="2"/></link>
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView>
  </road>
  <road id="2">
    <link><predecessor elementType="road" elementId="1"/></link>
    <planView><geometry s="0" x="10" y="0" hdg="0" length="10"/></planView>
  </road>
"""
    )
    issues = _legacy_scan(root)
    assert issues["multi_successor"] == []
    assert issues["multi_predecessor"] == []
    assert issues["self_links"] == []
    assert issues["zero_geometry"] == []
    assert issues["broken_junction_refs"] == []
    assert issues["endpoint_mismatch"] == []


# ---------------------------------------------------------------------------
# _remove_roads
# ---------------------------------------------------------------------------
def test_remove_roads_deletes_road_elements():
    root = _root('<road id="1"/><road id="2"/>')
    removed = _remove_roads(root, ["1"])
    assert removed == 1
    assert root.find("./road[@id='1']") is None
    assert root.find("./road[@id='2']") is not None


def test_remove_roads_also_removes_referencing_junction_connections():
    root = _root(
        """
  <road id="1"/><road id="2"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    _remove_roads(root, ["1"])
    junction = root.find("./junction[@id='10']")
    assert junction.findall("connection") == []


# ---------------------------------------------------------------------------
# prune() end-to-end (file-based)
# ---------------------------------------------------------------------------
def test_prune_nothing_to_remove_writes_original_copy(tmp_path):
    xodr_path = _write_xodr(
        tmp_path,
        """
  <road id="1">
    <link><successor elementType="road" elementId="2"/></link>
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView>
  </road>
  <road id="2">
    <link><predecessor elementType="road" elementId="1"/></link>
    <planView><geometry s="0" x="10" y="0" hdg="0" length="10"/></planView>
  </road>
""",
    )
    out_path, removed_ids = prune(xodr_path)
    assert removed_ids == []
    assert os.path.exists(out_path)
    assert out_path.endswith("_legacy_pruned.xodr")


def test_prune_removes_flagged_roads(tmp_path):
    xodr_path = _write_xodr(
        tmp_path,
        """
  <road id="1"/>
  <road id="2">
    <link><successor elementType="road" elementId="2"/></link>
  </road>
""",
    )
    out_path, removed_ids = prune(xodr_path)
    assert "1" in removed_ids  # zero geometry
    assert "2" in removed_ids  # self-link
    tree = ET.parse(out_path)
    assert tree.getroot().findall("road") == []


def test_prune_missing_input_raises(tmp_path):
    missing = os.path.join(str(tmp_path), "nope.xodr")
    with pytest.raises(FileNotFoundError):
        prune(missing)
