from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.topology.junction_connector_rebuild import (
    rebuild_displaced_junction_connectors_in_file,
)


def _write_xodr(path: Path, body: str) -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="" version="1.00" date="2026-04-28" north="0" south="0" east="0" west="0"/>
{body}
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def test_line_connector_rebuild_blocks_straight_chord_by_default(tmp_path: Path) -> None:
    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    report_path = tmp_path / "report.json"
    risk_path = tmp_path / "junction_connector_risk.json"
    _write_xodr(
        src,
        """
  <road name="incoming" length="100.0" id="1" junction="-1">
    <link><successor elementType="junction" elementId="10" contactPoint="start"/></link>
    <planView><geometry s="0" x="0" y="0" hdg="0" length="100"><line/></geometry></planView>
  </road>
  <road name="outgoing" length="100.0" id="2" junction="-1">
    <link/>
    <planView><geometry s="0" x="110" y="0" hdg="0" length="100"><line/></geometry></planView>
  </road>
  <road name="connector" length="40.0" id="100" junction="10">
    <link>
      <predecessor elementType="road" elementId="1" contactPoint="end"/>
      <successor elementType="road" elementId="2" contactPoint="start"/>
    </link>
    <planView><geometry s="0" x="70" y="0" hdg="0" length="40"><line/></geometry></planView>
  </road>
  <junction id="10">
    <connection id="0" incomingRoad="1" connectingRoad="100" contactPoint="start"/>
  </junction>
""",
    )

    report = rebuild_displaced_junction_connectors_in_file(
        src, out, report_path=report_path, risk_report_path=risk_path
    )

    assert report["attempted"] == 1
    assert report["rebuilt"] == 0
    assert report["reverted"] == 0
    assert report["blocked_connector_reconstruction"] == 1
    assert report["start_gap_over_threshold_before"] == 1
    assert report["start_gap_over_threshold_after"] == 1
    assert report["blocked_connector_candidates"][0]["code"] == "BLOCKED_CONNECTOR_RECONSTRUCTION"

    connector = ET.parse(out).getroot().find("./road[@id='100']")
    assert connector is not None
    geom = connector.find("./planView/geometry")
    assert geom is not None
    assert geom.find("line") is not None
    assert float(geom.get("x")) == 70.0
    assert float(geom.get("y")) == 0.0
    assert math.isclose(float(geom.get("length")), 40.0)

    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    assert risk["ok"] is False
    assert risk["failed_check_count"] == 2


def test_rebuild_parampoly3_connector_prefers_verified_arc(tmp_path: Path) -> None:
    src = tmp_path / "in_param.xodr"
    out = tmp_path / "out_param.xodr"
    _write_xodr(
        src,
        """
  <road name="incoming" length="10.0" id="1" junction="-1">
    <link><successor elementType="junction" elementId="10" contactPoint="start"/></link>
    <planView><geometry s="0" x="-10" y="0" hdg="0" length="10"><line/></geometry></planView>
  </road>
  <road name="outgoing" length="25.0" id="2" junction="-1">
    <link/>
    <planView><geometry s="0" x="10" y="5" hdg="0" length="25"><line/></geometry></planView>
  </road>
  <road name="connector" length="15.0" id="100" junction="10">
    <link>
      <predecessor elementType="road" elementId="1" contactPoint="end"/>
      <successor elementType="road" elementId="2" contactPoint="start"/>
    </link>
    <planView>
      <geometry s="0" x="0" y="20" hdg="-1.57079632679" length="15">
        <paramPoly3 aU="0" bU="15" cU="0" dU="0" aV="0" bV="0" cV="0" dV="0" pRange="normalized"/>
      </geometry>
    </planView>
  </road>
  <junction id="10">
    <connection id="0" incomingRoad="1" connectingRoad="100" contactPoint="start"/>
  </junction>
""",
    )

    report = rebuild_displaced_junction_connectors_in_file(src, out)

    assert report["attempted"] == 1
    assert report["rebuilt"] == 1
    assert report["geometry_written"] == {"arc": 1}
    assert report["start_gap_over_threshold_after"] == 0
    assert report["end_gap_over_tolerance_after"] == 0

    connector = ET.parse(out).getroot().find("./road[@id='100']")
    assert connector is not None
    geom = connector.find("./planView/geometry")
    assert geom is not None
    assert geom.find("arc") is not None
    assert math.isclose(float(geom.get("x")), 0.0)
    assert math.isclose(float(geom.get("y")), 0.0)
