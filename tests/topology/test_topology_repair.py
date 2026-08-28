"""Tests for ultimate_pipeline/topology/topology_repair.py.

Zero prior test coverage. `TopologyRepair.run()` is invoked on every real
pipeline run (STEP 3: Topology Repair, stage_03_topology_repair.py),
immediately before the junction-integrity gate -- so a bug here can
silently let broken links/junctions through to the CARLA-load step.

Note on scope: this module also defines `canonicalize_junction_connectors`,
a large multi-policy (A/B/D/E) connector-canonicalization algorithm. It is
NOT called anywhere in the codebase (confirmed via repo-wide grep: only
self-references inside topology_repair.py itself) -- it is dead code, not
part of any live pipeline path. Per this session's standing rule against
implementing/validating new topology-repair algorithms without deliberate,
separate authorization, this test file does not attempt to exercise or
certify that function; it is flagged here as a finding instead of being
fixed or extensively tested.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.topology_repair import TopologyRepair


def _root(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{xml_body}\n</OpenDRIVE>')


# ---------------------------------------------------------------------------
# _fix_links
# ---------------------------------------------------------------------------
def test_fix_links_removes_ref_to_missing_road():
    root = _root(
        '<road id="1"><link><successor elementType="road" elementId="999" '
        'contactPoint="start"/></link></road>'
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    assert link.find("successor") is None


def test_fix_links_removes_self_reference():
    root = _root(
        '<road id="1"><link><successor elementType="road" elementId="1" '
        'contactPoint="start"/></link></road>'
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    assert link.find("successor") is None


def test_fix_links_removes_ref_to_missing_junction():
    root = _root(
        '<road id="1"><link><predecessor elementType="junction" elementId="99" '
        'contactPoint="start"/></link></road>'
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    assert link.find("predecessor") is None


def test_fix_links_removes_unknown_element_type():
    root = _root(
        '<road id="1"><link><successor elementType="bogus" elementId="1" '
        'contactPoint="start"/></link></road>'
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    assert link.find("successor") is None


def test_fix_links_removes_exact_duplicate_entries():
    root = _root(
        """
  <road id="1">
    <link>
      <successor elementType="road" elementId="2" contactPoint="start"/>
      <successor elementType="road" elementId="2" contactPoint="start"/>
    </link>
  </road>
  <road id="2"/>
"""
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    successors = link.findall("successor")
    assert len(successors) == 1


def test_fix_links_keeps_valid_distinct_links():
    root = _root(
        """
  <road id="1">
    <link>
      <predecessor elementType="road" elementId="2" contactPoint="end"/>
      <successor elementType="road" elementId="3" contactPoint="start"/>
    </link>
  </road>
  <road id="2"/><road id="3"/>
"""
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    assert link.find("predecessor") is not None
    assert link.find("successor") is not None


def test_fix_links_keeps_valid_junction_link():
    root = _root(
        """
  <road id="1"><link><successor elementType="junction" elementId="10" contactPoint="start"/></link></road>
  <junction id="10"/>
"""
    )
    TopologyRepair._fix_links(root)
    link = root.find("./road[@id='1']/link")
    assert link.find("successor") is not None


def test_fix_links_road_without_link_element_no_crash():
    root = _root('<road id="1"/>')
    TopologyRepair._fix_links(root)  # must not raise
    assert root.find("./road[@id='1']/link") is None


# ---------------------------------------------------------------------------
# _fix_junctions
# ---------------------------------------------------------------------------
def test_fix_junctions_removes_connection_with_missing_road():
    root = _root(
        """
  <road id="1"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="999"/></junction>
"""
    )
    TopologyRepair._fix_junctions(root)
    junction = root.find("./junction[@id='10']")
    assert junction.findall("connection") == []


def test_fix_junctions_removes_self_connection():
    root = _root(
        """
  <road id="1"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="1"/></junction>
"""
    )
    TopologyRepair._fix_junctions(root)
    junction = root.find("./junction[@id='10']")
    assert junction.findall("connection") == []


def test_fix_junctions_removes_connection_with_missing_ids():
    root = _root('<junction id="10"><connection incomingRoad="" connectingRoad="2"/></junction>')
    TopologyRepair._fix_junctions(root)
    junction = root.find("./junction[@id='10']")
    assert junction.findall("connection") == []


def test_fix_junctions_removes_exact_duplicate_connections():
    root = _root(
        """
  <road id="1"/><road id="2"/>
  <junction id="10">
    <connection incomingRoad="1" connectingRoad="2" contactPoint="start"/>
    <connection incomingRoad="1" connectingRoad="2" contactPoint="start"/>
  </junction>
"""
    )
    TopologyRepair._fix_junctions(root)
    junction = root.find("./junction[@id='10']")
    assert len(junction.findall("connection")) == 1


def test_fix_junctions_keeps_valid_connection():
    root = _root(
        """
  <road id="1"/><road id="2"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    TopologyRepair._fix_junctions(root)
    junction = root.find("./junction[@id='10']")
    assert len(junction.findall("connection")) == 1


# ---------------------------------------------------------------------------
# _remove_empty_junctions
# ---------------------------------------------------------------------------
def test_remove_empty_junctions_deletes_junction_with_no_connections():
    root = _root('<junction id="10"/>')
    TopologyRepair._remove_empty_junctions(root)
    assert root.find("./junction[@id='10']") is None


def test_remove_empty_junctions_keeps_junction_with_connections():
    root = _root(
        """
  <road id="1"/><road id="2"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    TopologyRepair._remove_empty_junctions(root)
    assert root.find("./junction[@id='10']") is not None


# ---------------------------------------------------------------------------
# run(): full pipeline order (fix_links -> fix_junctions -> remove_empty_junctions)
# ---------------------------------------------------------------------------
def test_run_end_to_end_leaves_valid_topology_untouched():
    root = _root(
        """
  <road id="1"><link><successor elementType="road" elementId="2" contactPoint="start"/></link></road>
  <road id="2"><link><predecessor elementType="road" elementId="1" contactPoint="end"/></link></road>
  <junction id="10"><connection incomingRoad="1" connectingRoad="2"/></junction>
"""
    )
    TopologyRepair.run(root)
    assert root.find("./road[@id='1']/link/successor") is not None
    assert root.find("./junction[@id='10']") is not None
    assert len(root.find("./junction[@id='10']").findall("connection")) == 1


def test_run_junction_becomes_empty_after_fix_junctions_and_is_removed():
    """A junction whose only connection references a since-invalid road ends up
    empty after _fix_junctions and must be pruned by _remove_empty_junctions."""
    root = _root(
        """
  <road id="1"/>
  <junction id="10"><connection incomingRoad="1" connectingRoad="999"/></junction>
"""
    )
    TopologyRepair.run(root)
    assert root.find("./junction[@id='10']") is None


def test_run_does_not_raise_on_empty_map():
    root = _root("")
    TopologyRepair.run(root)  # must not raise
