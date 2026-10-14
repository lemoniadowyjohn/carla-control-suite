# tests/unit/test_opendrive_rebase.py
# -*- coding: utf-8 -*-
"""OC-38: centralized XODR local-frame rebase.

Regressions guard the single centralized engine in
``ultimate_pipeline.geometry.opendrive_rebase`` and its adoption by BOTH the
canonical map-of-record rebase (``scripts.regen_map_of_record._rebase_to_local``)
and the runtime tile builder
(``ultimate_pipeline.tiling.runtime_tile_builder``).

The historical defect: two divergent rebase implementations with disjoint
absolute-coordinate coverage. regen shifted only planView/geometry + object-
outline cornerGlobal; the tile builder shifted geometry + cornerGlobal +
positionInertial. Neither shifted ``<object>`` or ``<signal>`` x/y, so any map
carrying those kept global tmerc values while roads were localized -- the same
frame disagreement that previously produced a verified 7,665m building/road
drift. These tests pin the unified coverage set and the failure behavior.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import scripts.regen_map_of_record as regen
from ultimate_pipeline.geometry.opendrive_rebase import (
    UnboundedCoordinateError,
    planview_min_xy,
    rebase_xodr_coordinates,
)
from ultimate_pipeline.tiling.runtime_tile_builder import (
    RuntimeTileRequest,
    build_runtime_tile,
)

_DX = 832671.676
_DY = 5458671.104


def _global_frame_root() -> ET.Element:
    """Road geometry, building cornerGlobal, a crosswalk (s/t only), an object
    carrying x/y, a signal carrying x/y and an s/t-only signal, plus a
    positionInertial -- everything with an absolute header-frame coordinate."""
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", name="g", north="1", south="0", east="1", west="0")
    ET.SubElement(header, "geoReference").text = "+proj=tmerc"
    road = ET.SubElement(root, "road", id="1", length="100", junction="-1")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x=f"{_DX}", y=f"{_DY}", hdg="0", length="10")
    ET.SubElement(pv, "geometry", s="10", x=f"{_DX + 10}", y=f"{_DY}", hdg="0", length="10")

    road_objs = ET.SubElement(road, "objects")
    building = ET.SubElement(
        road_objs,
        "object",
        id="bld_1", type="building", s="0.0", t="0.0",
        orientation="absolute",
    )
    outline = ET.SubElement(building, "outline", id="0", fillType="concrete")
    ET.SubElement(outline, "cornerGlobal", x="832700.000", y="5458700.000", z="0.0")
    ET.SubElement(outline, "cornerGlobal", x="832710.000", y="5458700.000", z="0.0")
    ET.SubElement(
        road_objs,
        "object",
        id="xy_obj", type="pole", s="2.0", t="0.0", x="832750.500", y="5458750.500",
    )
    ET.SubElement(
        road_objs,
        "object",
        id="xw", type="crosswalk", s="3.0", t="0.0",
    )  # s/t only: must stay untouched
    ET.SubElement(
        road_objs,
        "positionInertial",
        x="832705.500", y="5458705.500", z="0.0",
    )

    signals = ET.SubElement(road, "signals")
    ET.SubElement(
        signals,
        "signal",
        id="s_xy", s="1.0", t="0.0", type="1000001", subtype="0", x="832690.000", y="5458680.000",
    )
    ET.SubElement(
        signals,
        "signal",
        id="s_st", s="2.0", t="0.0", type="1000001", subtype="0",
    )  # s/t only: must stay untouched
    return root


# ---------------------------------------------------------------------------
# A-C. Engine core: unified coverage set and derivation
# ---------------------------------------------------------------------------


def test_a_planview_min_xy_derives_local_origin():
    assert planview_min_xy(_global_frame_root()) == (_DX, _DY)


def test_b_engine_translates_every_geometry_and_corner_global_by_same_dx_dy():
    root = _global_frame_root()
    result = rebase_xodr_coordinates(root, dx=_DX, dy=_DY)
    assert result["dx"] == _DX
    assert result["dy"] == _DY

    geometries = root.findall(".//planView/geometry")
    assert [g.get("x") for g in geometries] == ["0.000000", "10.000000"]
    assert [g.get("y") for g in geometries] == ["0.000000", "0.000000"]

    corners = root.findall(".//object/outline/cornerGlobal")
    assert [(c.get("x"), c.get("y")) for c in corners] == [
        ("28.324000", "28.896000"),
        ("38.324000", "28.896000"),
    ]

    assert set(result["translated_elements"]) == {
        "planview_geometry",
        "corner_global",
        "position_inertial",
        "object_xy",
        "signal_xy",
    }


def test_c_optional_object_and_signal_xy_translated_but_st_tokens_left_alone():
    root = _global_frame_root()
    rebase_xodr_coordinates(root, dx=_DX, dy=_DY)
    by_id = {e.get("id"): e for e in root.findall(".//object")}
    assert by_id["xy_obj"].get("x") == "78.824000"
    assert by_id["xy_obj"].get("y") == "79.396000"
    # s/t-road-relative object stays byte-identical (no x/y introduced)
    assert by_id["xw"].get("x") is None
    assert by_id["xw"].get("y") is None

    sigs = {e.get("id"): e for e in root.findall(".//signal")}
    assert sigs["s_xy"].get("x") == "18.324000"
    assert sigs["s_xy"].get("y") == "8.896000"
    assert sigs["s_st"].get("x") is None

    pos = root.findall(".//positionInertial")
    assert [(p.get("x"), p.get("y")) for p in pos] == [("33.824000", "34.396000")]


# ---------------------------------------------------------------------------
# D-F. Fail-closed behavior on degenerate input (previously defaulted to 0)
# ---------------------------------------------------------------------------


def test_d_non_finite_geometry_coordinate_raises():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    ET.SubElement(road, "planView")
    ET.SubElement(
        ET.SubElement(road, "planView"),
        "geometry", s="0", x="nan", y="0", hdg="0", length="10",
    )
    with pytest.raises(UnboundedCoordinateError):
        planview_min_xy(root)
    with pytest.raises(UnboundedCoordinateError, match="non-finite"):
        rebase_xodr_coordinates(root, dx=1.0, dy=0.0)


def test_e_missing_geometry_raises():
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "road", id="1", junction="-1")
    with pytest.raises(UnboundedCoordinateError, match="no planView geometry"):
        planview_min_xy(root)


def test_f_non_numeric_geometry_coordinate_raises():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x="abc", y="0", hdg="0", length="10")
    with pytest.raises(UnboundedCoordinateError, match="non-numeric"):
        planview_min_xy(root)


# ---------------------------------------------------------------------------
# G-I. regen canonical path adopts the engine (coverage union + no gfx drift)
# ---------------------------------------------------------------------------


def _write(root: ET.Element, path: Path) -> None:
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_g_regen_rebase_adopts_full_coverage_union(tmp_path):
    src = tmp_path / "global.xodr"
    out = tmp_path / "local.xodr"
    _write(_global_frame_root(), src)
    report = regen._rebase_to_local(src, out)
    assert report["shifted"] is True
    assert report["dx"] == round(_DX, 3)
    assert report["dy"] == round(_DY, 3)

    out_root = ET.parse(out).getroot()
    assert [g.get("x") for g in out_root.findall(".//planView/geometry")] == [
        "0.000000",
        "10.000000",
    ]
    corners = out_root.findall(".//object/outline/cornerGlobal")
    assert [(c.get("x"), c.get("y")) for c in corners] == [
        ("28.324000", "28.896000"),
        ("38.324000", "28.896000"),
    ]
    xy_obj = out_root.find(".//object[@id='xy_obj']")
    assert (xy_obj.get("x"), xy_obj.get("y")) == ("78.824000", "79.396000")
    s_xy = out_root.find(".//signal[@id='s_xy']")
    assert (s_xy.get("x"), s_xy.get("y")) == ("18.324000", "8.896000")
    pos = out_root.findall(".//positionInertial")
    assert [(p.get("x"), p.get("y")) for p in pos] == [("33.824000", "34.396000")]

    offset = out_root.find("header/offset")
    assert float(offset.get("x")) == round(_DX, 3)
    assert float(offset.get("y")) == round(_DY, 3)
    assert report["translated_elements"] == {
        "planview_geometry": 2,
        "corner_global": 2,
        "position_inertial": 1,
        "object_xy": 1,
        "signal_xy": 1,
    }


def test_h_regen_rebase_noop_when_already_local_preserved(tmp_path):
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10", junction="-1")
    ET.SubElement(road, "planView")
    ET.SubElement(
        ET.SubElement(road, "planView"),
        "geometry", s="0", x="0.07", y="0.17", hdg="0", length="10",
    )
    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write(root, src)
    report = regen._rebase_to_local(src, out)
    assert report["shifted"] is False
    assert report["reason"] == "already_local"
    assert not out.exists()


def test_i_regen_rebase_aborts_on_degenerate_geometry_without_writing(tmp_path):
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x="inf", y="0", hdg="0", length="10")
    src = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write(root, src)
    with pytest.raises(UnboundedCoordinateError):
        regen._rebase_to_local(src, out)
    assert not out.exists()


# ---------------------------------------------------------------------------
# J. Runtime tile builder adopts the same engine
# ---------------------------------------------------------------------------


def _tile_source(root: ET.Element) -> ET.Element:
    road = ET.SubElement(root, "road", id="1", length="20", junction="-1")
    link = ET.SubElement(road, "link")
    ET.SubElement(link, "predecessor", elementType="road", elementId="0", contactPoint="end")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="20")
    ET.SubElement(ET.SubElement(road, "lanes") or road, "laneSection", s="0")
    return road


def test_j_runtime_tile_translates_the_same_absolute_coordinate_set(tmp_path):
    source = tmp_path / "source.xodr"
    output = tmp_path / "runtime.xodr"
    src_root = ET.Element("OpenDRIVE")
    header = ET.SubElement(src_root, "header", name="src", north="1", south="0", east="1", west="0")
    ET.SubElement(header, "geoReference").text = "+proj=tmerc"
    ET.SubElement(header, "offset", x="832671.676", y="5458671.104", z="0", hdg="0")
    road = ET.SubElement(src_root, "road", id="1", length="20", junction="-1")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0", x="500", y="0", hdg="0", length="20")
    lane_elem = ET.SubElement(road, "lanes")
    section = ET.SubElement(lane_elem, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    ET.SubElement(lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")

    objs = ET.SubElement(road, "objects")
    building = ET.SubElement(
        objs,
        "object", id="bld", type="building", s="0", t="0", orientation="absolute",
    )
    outline = ET.SubElement(building, "outline", id="0", fillType="concrete")
    ET.SubElement(outline, "cornerGlobal", x="600", y="0", z="0")
    ET.SubElement(objs, "object", id="pole", type="pole", s="1", t="0", x="700", y="0")
    signals = ET.SubElement(road, "signals")
    ET.SubElement(signals, "signal", id="s1", s="1", t="0", type="1000001", subtype="0", x="800", y="0")
    ET.ElementTree(src_root).write(source, encoding="utf-8", xml_declaration=True)

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

    out_root = ET.parse(output).getroot()
    geometry = out_root.find(".//planView/geometry")
    assert abs(float(geometry.get("x")) - (500 - 5.0)) < 1e-6
    corner = out_root.find(".//outline/cornerGlobal")
    assert abs(float(corner.get("x")) - (600 - 5.0)) < 1e-6
    pole = out_root.find(".//object[@id='pole']")
    assert abs(float(pole.get("x")) - (700 - 5.0)) < 1e-6
    sig = out_root.find(".//signal[@id='s1']")
    assert abs(float(sig.get("x")) - (800 - 5.0)) < 1e-6

    offset = out_root.find("header/offset")
    assert {k: offset.get(k) for k in ("x", "y", "z", "hdg")} == {
        "x": "0", "y": "0", "z": "0", "hdg": "0",
    }

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["runtime_tile"]["sha256"]
    assert manifest["local_frame"]["translation_from_source_xy_m"] == [5.0, 0.0]


# ---------------------------------------------------------------------------
# K. Real-map empirical: the pinned candidate's absolute-coordinate population
# ---------------------------------------------------------------------------


def test_k_real_map_candidate_coverage_matches_engine():
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_perception_map_of_record_20260916_232831.xodr"
    if not candidate.is_file():
        pytest.skip("real map-of-record candidate not present in this environment")
    root = ET.parse(candidate).getroot()
    objects = root.findall(".//object")
    signals = root.findall(".//signal")
    assert objects, "fixture must contain building/crosswalk objects"
    assert signals, "fixture must contain signals"
    # The pinned candidate uses s/t road-relative position metadata (no x/y on
    # object/signal); the engine's optional selectors must therefore be a no-op
    # and only geometry + cornerGlobal carry the absolute frame.
    for element in objects + signals:
        assert "x" not in element.attrib
        assert "y" not in element.attrib
    min_x, min_y = planview_min_xy(root)
    assert abs(min_x) < 1.0 and abs(min_y) < 1.0, "candidate must already be local"
    result = rebase_xodr_coordinates(root, dx=0.0, dy=0.0)
    assert set(result["translated_elements"]) == {"planview_geometry", "corner_global"}