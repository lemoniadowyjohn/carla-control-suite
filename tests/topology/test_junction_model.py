import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.topology.junction_model import (
    JunctionModel,
    JunctionValidator,
    LaneLink,
    ConnectingRoad,
    summarize_junctions,
)


SAMPLE_XODR = """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
  <junction id="1" name="Simple Junction">
    <connection id="0" incomingRoad="100" connectingRoad="200" contactPoint="start">
      <laneLink from="-1" to="-2"/>
      <laneLink from="-2" to="-1"/>
    </connection>
    <connection id="1" incomingRoad="101" connectingRoad="201" contactPoint="end">
      <laneLink from="1" to="1"/>
    </connection>
  </junction>
  <junction id="2" name="Complex">
    <connection id="0" incomingRoad="200" connectingRoad="300" contactPoint="start"/>
    <connection id="1" incomingRoad="200" connectingRoad="301" contactPoint="start"/>
  </junction>
  <road id="100"/>
  <road id="101"/>
  <road id="200"/>
  <road id="201"/>
  <road id="300"/>
  <road id="301"/>
</OpenDRIVE>"""


def test_lane_link_from_xml() -> None:
    elem = ET.fromstring('<laneLink from="-1" to="-2"/>')
    ll = LaneLink.from_xml(elem)
    assert ll.from_lane == -1
    assert ll.to_lane == -2


def test_connecting_road_from_xml() -> None:
    xml = '<connection id="0" incomingRoad="100" connectingRoad="200" contactPoint="start">' \
          '  <laneLink from="-1" to="-2"/>' \
          '</connection>'
    elem = ET.fromstring(xml)
    cr = ConnectingRoad.from_xml(elem)
    assert cr.connection_id == "0"
    assert cr.incoming_road == "100"
    assert cr.connecting_road == "200"
    assert cr.contact_point == "start"
    assert len(cr.lane_links) == 1
    assert cr.lane_links[0].from_lane == -1


def test_junction_model_from_xml() -> None:
    root = ET.fromstring(SAMPLE_XODR)
    je = root.findall("junction")[0]
    jm = JunctionModel.from_xml(je)
    assert jm.id == "1"
    assert jm.name == "Simple Junction"
    assert len(jm.connections) == 2
    assert "200" in jm.connecting_road_ids
    assert "100" in jm.incoming_road_ids


def test_junction_model_from_xodr_string() -> None:
    junctions = JunctionModel.from_xodr_string(SAMPLE_XODR)
    assert len(junctions) == 2
    assert junctions[0].id == "1"
    assert junctions[1].id == "2"


def test_junction_validator_connectivity_ok() -> None:
    junctions = JunctionModel.from_xodr_string(SAMPLE_XODR)
    road_ids = {"100", "101", "200", "201", "300", "301"}
    validator = JunctionValidator(junctions, road_ids)
    errors = validator.validate_connectivity()
    assert errors == []


def test_junction_validator_connectivity_missing_road() -> None:
    junctions = JunctionModel.from_xodr_string(SAMPLE_XODR)
    road_ids = {"100", "200", "300", "301"}
    validator = JunctionValidator(junctions, road_ids)
    errors = validator.validate_connectivity()
    assert any("101" in e and "not found" in e for e in errors)
    assert any("201" in e and "not found" in e for e in errors)


def test_junction_validator_no_duplicate_connections() -> None:
    xodr = """<?xml version="1.0"?>
<OpenDRIVE>
  <junction id="1">
    <connection id="0" incomingRoad="100" connectingRoad="200" contactPoint="start"/>
    <connection id="1" incomingRoad="100" connectingRoad="200" contactPoint="start"/>
  </junction>
  <road id="100"/>
  <road id="200"/>
</OpenDRIVE>"""
    junctions = JunctionModel.from_xodr_string(xodr)
    validator = JunctionValidator(junctions, {"100", "200"})
    errors = validator.validate_no_duplicate_connections()
    assert len(errors) >= 1
    assert "duplicate" in errors[0]


def test_junction_validator_lane_links_out_of_range() -> None:
    xodr = """<?xml version="1.0"?>
<OpenDRIVE>
  <junction id="1">
    <connection id="0" incomingRoad="100" connectingRoad="200" contactPoint="start">
      <laneLink from="-5" to="-1"/>
    </connection>
  </junction>
  <road id="100"/>
  <road id="200"/>
</OpenDRIVE>"""
    junctions = JunctionModel.from_xodr_string(xodr)
    validator = JunctionValidator(junctions, {"100", "200"})
    errors = validator.validate_lane_links({"100": 3})
    assert len(errors) >= 1
    assert "exceeds" in errors[0]


def test_find_by_connecting_road() -> None:
    junctions = JunctionModel.from_xodr_string(SAMPLE_XODR)
    j1 = junctions[0]
    results = j1.find_by_connecting_road("200")
    assert len(results) == 1
    assert results[0].connecting_road == "200"


def test_find_by_incoming_road() -> None:
    junctions = JunctionModel.from_xodr_string(SAMPLE_XODR)
    j2 = junctions[1]
    results = j2.find_by_incoming_road("200")
    assert len(results) == 2


def test_summarize_junctions() -> None:
    junctions = JunctionModel.from_xodr_string(SAMPLE_XODR)
    summary = summarize_junctions(junctions)
    assert summary["total_junctions"] == 2
    assert summary["unique_connecting_roads"] == 4
    assert summary["unique_incoming_roads"] == 3
