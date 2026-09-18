# tests/unit/test_runtime_tile_referential_integrity.py
# -*- coding: utf-8 -*-
"""OC-39: runtime-tile referential integrity.

validate_runtime_tile previously certified "PASS" while checking only roads,
driving lanes, and the three road/junction reference families. It never
verified:

  - controllers referencing signals that no longer exist in the tile
    (a controller clone left behind after its road was pruned);
  - junction connection laneLinks whose from/to lane ids do not exist on the
    referenced incoming/connecting roads (a CARLA load-time crash source);
  - duplicate road/junction/signal ids, which make every reference ambiguous.

These tests pin the extended fail-closed referential contract. build_runtime_tile
keeps the exact same "static PASS or artifact deleted" behavior: a tile that
fails any of the new checks is never emitted.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.tiling.runtime_tile_builder import (
    RuntimeTileRequest,
    build_runtime_tile,
    validate_runtime_tile,
)


def _road(
    road_id: str,
    x: float,
    *,
    lane_ids: list[str] | None = None,
    lane_links: list[dict[str, str]] | None = None,
) -> ET.Element:
    road = ET.Element("road", id=road_id, length="20", junction="-1")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x=str(x), y="0", hdg="0", length="20")
    ET.SubElement(pv, "line")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none", level="false")
    right = ET.SubElement(section, "right")
    for lane_id in lane_ids or ["-1"]:
        lane = ET.SubElement(right, "lane", id=lane_id, type="driving", level="false")
        ET.SubElement(lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    if lane_links:
        parent = ET.SubElement(road, "link")
        for lr in lane_links:
            ET.SubElement(
                parent,
                lr["tag"],
                elementType=lr["elementType"],
                elementId=lr["elementId"],
                contactPoint="end",
            )
    return road


def _junction(junction_id: str, incoming: str, connecting: str, *, lane_link_from: str = "-1", lane_link_to: str = "-1") -> ET.Element:
    junction = ET.Element("junction", id=junction_id)
    connection = ET.SubElement(
        junction,
        "connection",
        id="0",
        incomingRoad=incoming,
        connectingRoad=connecting,
        contactPoint="start",
    )
    ET.SubElement(connection, "laneLink", **{"from": lane_link_from, "to": lane_link_to})
    return junction


def _write(root: ET.Element, path: Path) -> None:
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _tile_root(*, roads: list[ET.Element] | None = None, junctions: list[ET.Element] | None = None, controllers: list[ET.Element] | None = None) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", name="tile", north="40", south="-20", east="40", west="-20")
    ET.SubElement(header, "offset", x="0", y="0", z="0", hdg="0")
    for road in roads or []:
        root.append(road)
    for junction in junctions or []:
        root.append(junction)
    for controller in controllers or []:
        root.append(controller)
    return root


# ---------------------------------------------------------------------------
# A-D. New failure families, validated as standalone XODR files
# ---------------------------------------------------------------------------


def test_a_dangling_controller_ref_fails(tmp_path):
    road = _road("1", 0)
    signals = ET.SubElement(road, "signals")
    ET.SubElement(signals, "signal", id="keep", s="1", t="0", type="1000001", subtype="0")
    controller = ET.Element("controller", id="c1")
    ET.SubElement(controller, "control", signalId="keep", type="0")
    ET.SubElement(controller, "control", signalId="ghost", type="0")
    tile = tmp_path / "tile.xodr"
    _write(_tile_root(roads=[road], controllers=[controller]), tile)

    result = validate_runtime_tile(tile)
    assert result["status"] == "FAIL"
    assert "dangling_controller_refs" in result["failures"]
    assert result["dangling_controller_refs"] == [{"controller_id": "c1", "signal_id": "ghost"}]


def test_b_invalid_connection_lane_link_fails(tmp_path):
    road1 = _road("1", 0, lane_ids=["-1", "-2"])
    road2 = _road("2", 10, lane_ids=["-1"])
    junction = _junction("j1", incoming="1", connecting="2", lane_link_to="999")
    tile = tmp_path / "tile.xodr"
    _write(_tile_root(roads=[road1, road2], junctions=[junction]), tile)

    result = validate_runtime_tile(tile)
    assert result["status"] == "FAIL"
    assert "invalid_connection_lane_links" in result["failures"]
    assert result["invalid_connection_lane_links"] == [
        {
            "junction_id": "j1",
            "connection_id": "0",
            "incomingRoad": "1",
            "connectingRoad": "2",
            "from": "-1",
            "to": "999",
        }
    ]


def test_c_invalid_from_lane_and_missing_road_lanes_fail(tmp_path):
    road1 = _road("1", 0, lane_ids=["-1"])
    road2 = _road("2", 10, lane_ids=["-1"])
    junction = _junction("j1", incoming="1", connecting="2", lane_link_from="77", lane_link_to="-1")
    tile = tmp_path / "tile.xodr"
    _write(_tile_root(roads=[road1, road2], junctions=[junction]), tile)
    result = validate_runtime_tile(tile)
    assert result["status"] == "FAIL"
    assert result["invalid_connection_lane_links"][0]["from"] == "77"


def test_d_duplicate_road_and_junction_ids_fail(tmp_path):
    tile = tmp_path / "tile.xodr"
    root = _tile_root(
        roads=[_road("7", 0), _road("7", 30)],
        junctions=[_junction("j9", "1", "2"), _junction("j9", "3", "4")],
    )
    _write(root, tile)
    result = validate_runtime_tile(tile)
    assert result["status"] == "FAIL"
    assert "duplicate_element_ids" in result["failures"]
    assert result["duplicate_road_ids"] == ["7"]
    assert result["duplicate_junction_ids"] == ["j9"]


def test_d2_duplicate_signal_ids_are_reported_but_do_not_fail(tmp_path):
    road = _road("1", 0)
    signals = ET.SubElement(road, "signals")
    ET.SubElement(signals, "signal", id="dup", s="1", t="0", type="1000001", subtype="0")
    ET.SubElement(signals, "signal", id="dup", s="2", t="0", type="1000001", subtype="0")
    tile = tmp_path / "tile.xodr"
    _write(_tile_root(roads=[road]), tile)
    result = validate_runtime_tile(tile)
    assert result["status"] == "PASS"
    assert result["duplicate_signal_ids"] == ["dup"]


# ---------------------------------------------------------------------------
# E-F. build_runtime_tile applies the new contract (delete-on-fail)
# ---------------------------------------------------------------------------


def test_e_build_runtime_tile_rejects_broken_lane_link_and_emits_nothing(tmp_path):
    source = tmp_path / "source.xodr"
    road1 = _road("1", 0)
    signal_el = ET.SubElement(ET.SubElement(road1, "signals"), "signal", id="s1", s="1", t="0", type="1000001", subtype="0")
    road2 = _road("2", 10)
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", name="src")
    ET.SubElement(header, "offset", x="0", y="0", z="0", hdg="0")
    root.append(road1)
    root.append(road2)
    root.append(_junction("j1", "1", "2", lane_link_to="999"))
    _write(root, source)
    if signal_el.get("id") != "s1":
        raise AssertionError("unreachable")

    output = tmp_path / "runtime.xodr"
    with pytest.raises(RuntimeError, match="invalid_connection_lane_links"):
        build_runtime_tile(
            RuntimeTileRequest(
                input_xodr=source,
                output_xodr=output,
                center_x=5.0,
                center_y=0.0,
                tile_size_m=1000.0,
                buffer_m=0.0,
            )
        )
    assert not output.exists()


def test_f_build_runtime_tile_passes_wellformed_referential_tile(tmp_path):
    source = tmp_path / "source.xodr"
    road1 = _road("1", 0, lane_ids=["-1", "-2"])
    signals = ET.SubElement(road1, "signals")
    ET.SubElement(signals, "signal", id="s1", s="1", t="0", type="1000001", subtype="0")
    road2 = _road("2", 10)
    controller = ET.Element("controller", id="c1")
    ET.SubElement(controller, "control", signalId="s1", type="0")
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", name="src")
    ET.SubElement(header, "offset", x="0", y="0", z="0", hdg="0")
    root.append(road1)
    root.append(road2)
    root.append(_junction("j1", "1", "2"))
    root.append(controller)
    _write(root, source)

    output = tmp_path / "runtime.xodr"
    result = build_runtime_tile(
        RuntimeTileRequest(
            input_xodr=source,
            output_xodr=output,
            center_x=5.0,
            center_y=0.0,
            tile_size_m=1000.0,
            buffer_m=0.0,
        )
    )
    assert result.static_validation["status"] == "PASS"
    assert output.exists()
    assert result.static_validation["dangling_controller_refs"] == []
    assert result.static_validation["invalid_connection_lane_links"] == []


def test_g_validate_reports_clean_summary_fields_on_pass(tmp_path):
    road1 = _road("1", 0, lane_ids=["-1", "-2"])
    road2 = _road("2", 10)
    tile = tmp_path / "tile.xodr"
    _write(_tile_root(roads=[road1, road2], junctions=[_junction("j1", "1", "2")]), tile)
    result = validate_runtime_tile(tile)
    assert result["status"] == "PASS"
    assert result["failures"] == []
    assert result["dangling_controller_refs"] == []
    assert result["invalid_connection_lane_links"] == []
    assert result["duplicate_road_ids"] == []
    assert result["duplicate_junction_ids"] == []