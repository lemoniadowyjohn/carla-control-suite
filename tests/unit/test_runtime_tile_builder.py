"""Contract tests for standalone, CARLA-loadable runtime tiles.

These tests deliberately model the dependency the analytical tiler does not
need: a junction connector and its approach/exit must travel together, while
ordinary links beyond the selected runtime neighbourhood become clean map
boundaries rather than dangling OpenDRIVE references.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tiling.runtime_tile_builder import (
    RuntimeTileRequest,
    build_runtime_tile,
    validate_runtime_tile,
)


def _road(
    road_id: str,
    x: float,
    *,
    junction: str = "-1",
    predecessor: tuple[str, str] | None = None,
    successor: tuple[str, str] | None = None,
    signal_id: str | None = None,
) -> ET.Element:
    road = ET.Element("road", id=road_id, length="20", junction=junction)
    link = ET.SubElement(road, "link")
    if predecessor:
        ET.SubElement(
            link,
            "predecessor",
            elementType=predecessor[0],
            elementId=predecessor[1],
            contactPoint="end",
        )
    if successor:
        ET.SubElement(
            link,
            "successor",
            elementType=successor[0],
            elementId=successor[1],
            contactPoint="start",
        )
    plan_view = ET.SubElement(road, "planView")
    geometry = ET.SubElement(
        plan_view,
        "geometry",
        s="0",
        x=str(x),
        y="0",
        hdg="0",
        length="20",
    )
    ET.SubElement(geometry, "line")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    center = ET.SubElement(section, "center")
    ET.SubElement(center, "lane", id="0", type="none", level="false")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    lane_link = ET.SubElement(lane, "link")
    if predecessor:
        ET.SubElement(lane_link, "predecessor", id="-1")
    if successor:
        ET.SubElement(lane_link, "successor", id="-1")
    ET.SubElement(lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    if signal_id:
        signals = ET.SubElement(road, "signals")
        ET.SubElement(
            signals,
            "signal",
            id=signal_id,
            s="1",
            t="0",
            dynamic="yes",
            orientation="+",
            type="1000001",
            subtype="0",
        )
    return road


def _write_source(path: Path) -> None:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", name="source", north="100", south="0", east="100", west="0")
    ET.SubElement(header, "geoReference").text = "+proj=tmerc"
    root.append(_road("1", 0, successor=("junction", "10"), signal_id="signal-1"))
    root.append(
        _road(
            "2",
            20,
            junction="10",
            predecessor=("road", "1"),
            successor=("road", "3"),
        )
    )
    root.append(_road("3", 40, predecessor=("junction", "10"), successor=("road", "4")))
    root.append(_road("4", 500, predecessor=("road", "3")))
    junction = ET.SubElement(root, "junction", id="10", name="junction-10")
    connection = ET.SubElement(
        junction,
        "connection",
        id="0",
        incomingRoad="1",
        connectingRoad="2",
        contactPoint="start",
    )
    ET.SubElement(connection, "laneLink", **{"from": "-1", "to": "-1"})
    controller = ET.SubElement(root, "controller", id="controller-1", name="controller-1")
    ET.SubElement(controller, "control", signalId="signal-1", type="0")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_runtime_tile_closes_junction_and_scrubs_outer_boundary(tmp_path: Path) -> None:
    source = tmp_path / "source.xodr"
    output = tmp_path / "runtime.xodr"
    _write_source(source)
    source_hash_before = hashlib.sha256(source.read_bytes()).hexdigest()

    result = build_runtime_tile(
        RuntimeTileRequest(
            input_xodr=source,
            output_xodr=output,
            center_x=5.0,
            center_y=0.0,
            tile_size_m=20.0,
            buffer_m=0.0,
        )
    )

    assert result.static_validation["status"] == "PASS"
    assert result.manifest_path.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash_before

    root = ET.parse(output).getroot()
    assert [road.get("id") for road in root.findall("road")] == ["1", "2", "3"]
    assert [junction.get("id") for junction in root.findall("junction")] == ["10"]
    assert [controller.get("id") for controller in root.findall("controller")] == ["controller-1"]

    exit_road = root.find("road[@id='3']")
    assert exit_road is not None
    assert exit_road.find("./link/successor") is None
    assert exit_road.find("./lanes/laneSection/right/lane/link/successor") is None

    header = root.find("header")
    assert header is not None
    assert header.get("geometryFrozen") is None
    assert header.find("geoReference") is None
    assert float(exit_road.find("./planView/geometry").get("x")) == 35.0

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "READY_FOR_LIVE_CARLA_VALIDATION"
    assert manifest["source"]["sha256"] == source_hash_before
    assert manifest["runtime_tile"]["road_count"] == 3
    assert manifest["closure"]["boundary_road_links_removed"] == 1
    assert manifest["closure"]["boundary_lane_links_removed"] == 1


def test_runtime_tile_validator_rejects_a_dangling_road_link(tmp_path: Path) -> None:
    source = tmp_path / "source.xodr"
    output = tmp_path / "runtime.xodr"
    _write_source(source)
    build_runtime_tile(
        RuntimeTileRequest(
            input_xodr=source,
            output_xodr=output,
            center_x=5.0,
            center_y=0.0,
            tile_size_m=20.0,
            buffer_m=0.0,
        )
    )

    tree = ET.parse(output)
    ET.SubElement(
        tree.getroot().find("road[@id='3']/link"),
        "successor",
        elementType="road",
        elementId="missing",
        contactPoint="start",
    )
    tree.write(output, encoding="utf-8", xml_declaration=True)

    validation = validate_runtime_tile(output)
    assert validation["status"] == "FAIL"
    assert validation["dangling_road_links"] == [{"road_id": "3", "target_id": "missing"}]


def test_runtime_tile_rejects_a_closure_larger_than_the_explicit_limit(tmp_path: Path) -> None:
    source = tmp_path / "source.xodr"
    _write_source(source)

    try:
        build_runtime_tile(
            RuntimeTileRequest(
                input_xodr=source,
                output_xodr=tmp_path / "runtime.xodr",
                center_x=5.0,
                center_y=0.0,
                tile_size_m=20.0,
                buffer_m=0.0,
                max_closure_roads=2,
            )
        )
    except RuntimeError as exc:
        assert "closure exceeds max_closure_roads" in str(exc)
    else:
        raise AssertionError("runtime tile builder must fail closed on excessive closure")


def test_runtime_tile_rejects_vertical_or_rotated_source_offset(tmp_path: Path) -> None:
    source = tmp_path / "source.xodr"
    _write_source(source)
    tree = ET.parse(source)
    ET.SubElement(tree.getroot().find("header"), "offset", x="100", y="200", z="0", hdg="0.1")
    tree.write(source, encoding="utf-8", xml_declaration=True)

    try:
        build_runtime_tile(
            RuntimeTileRequest(
                input_xodr=source,
                output_xodr=tmp_path / "runtime.xodr",
                center_x=5.0,
                center_y=0.0,
                tile_size_m=20.0,
            )
        )
    except RuntimeError as exc:
        assert "unsupported non-zero header offset z or hdg" in str(exc)
    else:
        raise AssertionError("runtime tile builder must reject unsupported source transforms")


def test_runtime_tile_rebases_xy_source_header_offset_into_its_local_frame(tmp_path: Path) -> None:
    source = tmp_path / "source.xodr"
    output = tmp_path / "runtime.xodr"
    _write_source(source)
    tree = ET.parse(source)
    ET.SubElement(tree.getroot().find("header"), "offset", x="832671.676", y="5458671.104", z="0", hdg="0")
    tree.write(source, encoding="utf-8", xml_declaration=True)

    result = build_runtime_tile(
        RuntimeTileRequest(
            input_xodr=source,
            output_xodr=output,
            center_x=5.0,
            center_y=0.0,
            tile_size_m=20.0,
            buffer_m=0.0,
        )
    )

    header = ET.parse(output).getroot().find("header")
    assert header is not None
    offset = header.find("offset")
    assert offset is not None
    assert {key: offset.get(key) for key in ("x", "y", "z", "hdg")} == {
        "x": "0",
        "y": "0",
        "z": "0",
        "hdg": "0",
    }
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["local_frame"]["source_header_offset_xy_m"] == [832671.676, 5458671.104]
