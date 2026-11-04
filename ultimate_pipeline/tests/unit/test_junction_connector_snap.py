# ultimate_pipeline/tools/junction_connector_snap.py -- zero prior test
# coverage. Standalone CLI repair tool (not imported by the live pipeline)
# that nudges a junction connector road's planView geometry poses to align
# with its incoming road's endpoint.
#
# Real bug found: snap_junction_connectors() always read the connecting
# road's "start" pose as the attach point, ignoring the <connection>
# element's own contactPoint attribute. contactPoint="end" is a real,
# actively-used value in this codebase's junction connectors (confirmed by
# topology/junction_connector_rebuild.py's explicit "end" handling and its
# tests) -- for such connections, the connecting road's true attach point
# is its END geometry, not its start. The buggy code would compare the
# wrong point for the gap check and, if judged "too far", snap+rechain the
# connector's true start (the OTHER, unrelated end) to the incoming road,
# corrupting an already-correct connector.
#
# Fix: read contactPoint from the <connection> element; for "end" (which
# this narrow tool cannot safely rechain -- that needs backward geometry
# propagation, only implemented in the full topology/
# junction_connector_rebuild.py rebuilder), skip the connector rather than
# silently snapping the wrong end. Only "start" (the case this tool's
# existing forward-rechain logic actually handles correctly) is repaired.
from __future__ import annotations

import xml.etree.ElementTree as ET
import math

import pytest

from ultimate_pipeline.tools.junction_connector_snap import snap_junction_connectors
from ultimate_pipeline.tools import junction_connector_snap as snap_module


def _road(road_id: str, junction: str, x0: float, y0: float, hdg0: float, length: float) -> str:
    return (
        f'<road name="R{road_id}" length="{length}" id="{road_id}" junction="{junction}">'
        f'<planView>'
        f'<geometry s="0" x="{x0}" y="{y0}" hdg="{hdg0}" length="{length}"><line/></geometry>'
        f'</planView>'
        f'<lanes><laneSection s="0"><center><lane id="0" type="none"/></center></laneSection></lanes>'
        f'</road>'
    )


def _xodr_with_connection(
    *,
    incoming: str,
    connecting_junction: str,
    connecting_pose,
    connecting_length: float,
    contact_point: str,
) -> ET.Element:
    cx, cy, chdg = connecting_pose
    exit_x = cx + connecting_length * math.cos(chdg)
    exit_y = cy + connecting_length * math.sin(chdg)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  {incoming}
  <road name="R9" length="{connecting_length}" id="9" junction="{connecting_junction}">
    <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
    <planView><geometry s="0" x="{cx}" y="{cy}" hdg="{chdg}" length="{connecting_length}"><line/></geometry></planView>
    <lanes><laneSection s="0"><center><lane id="0" type="none"/></center></laneSection></lanes>
  </road>
  {_road("2", "-1", exit_x, exit_y, chdg, 10.0)}
  <junction id="{connecting_junction}">
    <connection id="0" incomingRoad="1" connectingRoad="9" contactPoint="{contact_point}">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
</OpenDRIVE>
"""
    return ET.fromstring(xml)


def test_snaps_displaced_connector_start_when_contact_point_start():
    # Incoming road 1: straight line from (0,0) heading 0, length 10 -> end at (10,0).
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    # Connector road 9 (contactPoint=start): its start is displaced 5m away
    # from incoming's end (10,0) -- beyond max_gap_m default of 2.0.
    root = _xodr_with_connection(
        incoming=incoming,
        connecting_junction="100",
        connecting_pose=(15.0, 0.0, 0.0),
        connecting_length=8.0,
        contact_point="start",
    )

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_examined"] == 1
    assert result["connectors_snapped"] == 1
    assert result["skipped_end_contact_point"] == 0

    connecting = root.find(".//road[@id='9']")
    geom = connecting.find("./planView/geometry")
    assert float(geom.get("x")) == pytest.approx(10.0)
    assert float(geom.get("y")) == pytest.approx(0.0)


def test_skips_contact_point_end_instead_of_snapping_wrong_end():
    # Same displaced-connector setup, but contactPoint="end" -- the tool
    # must NOT touch this connector's start geometry (that would corrupt
    # its true attach point, which is its END, not its start).
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    root = _xodr_with_connection(
        incoming=incoming,
        connecting_junction="100",
        connecting_pose=(15.0, 0.0, 0.0),
        connecting_length=8.0,
        contact_point="end",
    )
    connecting_before = root.find(".//road[@id='9']/planView/geometry")
    x_before, y_before = connecting_before.get("x"), connecting_before.get("y")

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_examined"] == 0
    assert result["connectors_snapped"] == 0
    assert result["skipped_end_contact_point"] == 1

    connecting_after = root.find(".//road[@id='9']/planView/geometry")
    assert connecting_after.get("x") == x_before
    assert connecting_after.get("y") == y_before


def test_no_snap_when_already_within_max_gap():
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    root = _xodr_with_connection(
        incoming=incoming,
        connecting_junction="100",
        connecting_pose=(10.5, 0.0, 0.0),  # 0.5m gap, under default 2.0
        connecting_length=8.0,
        contact_point="start",
    )

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_examined"] == 1
    assert result["connectors_snapped"] == 0


def test_rechains_multi_segment_connector_after_snap():
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  {incoming}
  <road name="R9" length="16.0" id="9" junction="100">
    <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
    <planView>
      <geometry s="0" x="15.0" y="0.0" hdg="0.0" length="8.0"><line/></geometry>
      <geometry s="8" x="23.0" y="0.0" hdg="0.0" length="8.0"><line/></geometry>
    </planView>
    <lanes><laneSection s="0"><center><lane id="0" type="none"/></center></laneSection></lanes>
  </road>
  {_road("2", "-1", 31.0, 0.0, 0.0, 10.0)}
  <junction id="100">
    <connection id="0" incomingRoad="1" connectingRoad="9" contactPoint="start">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
</OpenDRIVE>
"""
    root = ET.fromstring(xml)

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_snapped"] == 1
    assert result["geometries_rechained"] == 1

    geoms = root.findall(".//road[@id='9']/planView/geometry")
    assert float(geoms[0].get("x")) == pytest.approx(10.0)
    # The source-stage refit replaces the multi-segment connector with one
    # Hermite segment so both declared ends remain anchored.
    assert len(geoms) == 1
    assert geoms[0].find("paramPoly3") is not None
    assert result["connector_pose_reports"][0]["exit_error_after_m"] == pytest.approx(0.0)


def test_non_connector_road_incoming_side_ignored():
    # connectingRoad has junction="-1" (not actually a connector) -- must
    # be skipped entirely, not examined.
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    root = _xodr_with_connection(
        incoming=incoming,
        connecting_junction="-1",
        connecting_pose=(15.0, 0.0, 0.0),
        connecting_length=8.0,
        contact_point="start",
    )

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_examined"] == 0
    assert result["connectors_snapped"] == 0


def test_missing_incoming_road_counted_and_skipped():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <junction id="100">
    <connection id="0" incomingRoad="404" connectingRoad="9" contactPoint="start">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
</OpenDRIVE>
"""
    root = ET.fromstring(xml)

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["skipped_missing_incoming"] == 1
    assert result["connectors_examined"] == 0


def test_defaults_to_start_when_contact_point_attribute_absent():
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  {incoming}
  <road name="R9" length="8.0" id="9" junction="100">
    <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
    <planView><geometry s="0" x="15.0" y="0.0" hdg="0.0" length="8.0"><line/></geometry></planView>
    <lanes><laneSection s="0"><center><lane id="0" type="none"/></center></laneSection></lanes>
  </road>
  {_road("2", "-1", 23.0, 0.0, 0.0, 10.0)}
  <junction id="100">
    <connection id="0" incomingRoad="1" connectingRoad="9">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
</OpenDRIVE>
"""
    root = ET.fromstring(xml)

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["skipped_end_contact_point"] == 0
    assert result["connectors_snapped"] == 1


def test_refit_preserves_exit_pose_for_displaced_parampoly3_connector():
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    xml = f"""<OpenDRIVE>
      {incoming}
      <road name="connector" length="10" id="9" junction="100">
        <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
        <planView><geometry s="0" x="15" y="0" hdg="0" length="10">
          <paramPoly3 aU="0" bU="10" cU="0" dU="0" aV="0" bV="0" cV="0" dV="0" pRange="normalized"/>
        </geometry></planView>
        <lanes><laneSection s="0"><center><lane id="0" type="none"/></center></laneSection></lanes>
      </road>
      {_road("2", "-1", 25.0, 0.0, 0.0, 10.0)}
      <junction id="100"><connection id="0" incomingRoad="1" connectingRoad="9" contactPoint="start"/></junction>
    </OpenDRIVE>"""
    root = ET.fromstring(xml)

    result = snap_junction_connectors(root, max_gap_m=2.0)

    connector = root.find(".//road[@id='9']")
    start = connector.find("./planView/geometry")
    assert result["connectors_snapped"] == 1
    assert start.find("paramPoly3") is not None
    assert float(start.get("x")) == pytest.approx(10.0)
    assert result["connector_pose_reports"][0]["entry_error_after_m"] == pytest.approx(0.0)
    assert result["connector_pose_reports"][0]["exit_error_after_m"] == pytest.approx(0.0)


def test_refuses_rotation_without_a_topology_declared_exit_anchor():
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    root = _xodr_with_connection(
        incoming=incoming, connecting_junction="100", connecting_pose=(15.0, 0.0, 0.0),
        connecting_length=8.0, contact_point="start",
    )
    connector = root.find(".//road[@id='9']")
    connector.remove(connector.find("./link"))
    before_x = connector.find("./planView/geometry").get("x")

    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_snapped"] == 0
    assert result["skipped_missing_exit_anchor"] == 1
    assert connector.find("./planView/geometry").get("x") == before_x


def test_refit_rolls_back_when_canonical_endpoint_validation_fails(monkeypatch):
    incoming = _road("1", "-1", 0.0, 0.0, 0.0, 10.0)
    root = _xodr_with_connection(
        incoming=incoming, connecting_junction="100", connecting_pose=(15.0, 0.0, 0.0),
        connecting_length=8.0, contact_point="start",
    )
    connector = root.find(".//road[@id='9']")
    before_geom = connector.find("./planView/geometry")
    before = (dict(before_geom.attrib), before_geom[0].tag, dict(before_geom[0].attrib))
    original = snap_module._canonical_connector_poses
    calls = {"count": 0}

    def fail_after_before(road):
        calls["count"] += 1
        if calls["count"] == 2:
            raise ValueError("forced validation failure")
        return original(road)

    monkeypatch.setattr(snap_module, "_canonical_connector_poses", fail_after_before)
    result = snap_junction_connectors(root, max_gap_m=2.0)

    assert result["connectors_snapped"] == 0
    assert result["skipped_refit_validation"] == 1
    after_geom = connector.find("./planView/geometry")
    assert (dict(after_geom.attrib), after_geom[0].tag, dict(after_geom[0].attrib)) == before
