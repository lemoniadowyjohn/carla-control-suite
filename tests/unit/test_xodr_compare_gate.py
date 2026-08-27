"""ultimate_pipeline/tools/xodr_compare_gate.py -- the CRS-comparability gate that decides
whether two OpenDRIVE files (e.g. manual vs. auto-generated maps) can be validly compared for
domain-gap measurement. Wired into run_perception_pair.py. Fully stdlib-only, no CARLA
dependency. This session's history includes multiple real CRS/frame-shift bugs (bare-tmerc
contract, the osm_polygon_loader.py building corner frame-shift bug) -- a bug in THIS gate could
let a coordinate-mismatched comparison silently pass as "domain gap" instead of being refused.
Found via an expanded orphaned-.pyc sweep of the top-level tests/ directory (the original
tests/test_xodr_compare_gate.py no longer exists on this branch, and the module had zero
coverage anywhere on it).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tools.xodr_compare_gate import (
    _as_float,
    _bounds_sanity,
    _finite,
    _parse_xodr_header,
    build_report,
)


def _write_xodr(
    path: Path,
    *,
    georef: str | None = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +datum=WGS84",
    north=1000.0, south=0.0, east=1000.0, west=0.0,
    offset=None,
) -> None:
    root = ET.Element("OpenDRIVE")
    header_attrs = {}
    if north is not None:
        header_attrs["north"] = str(north)
    if south is not None:
        header_attrs["south"] = str(south)
    if east is not None:
        header_attrs["east"] = str(east)
    if west is not None:
        header_attrs["west"] = str(west)
    header = ET.SubElement(root, "header", **header_attrs)
    if georef is not None:
        geo = ET.SubElement(header, "geoReference")
        geo.text = georef
    if offset is not None:
        ET.SubElement(header, "offset", x=str(offset[0]), y=str(offset[1]), z="0", hdg="0")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# _as_float / _finite
# ---------------------------------------------------------------------------

def test_as_float_none_returns_none():
    assert _as_float(None) is None


def test_as_float_valid_string_parses():
    assert _as_float("3.14") == 3.14


def test_as_float_invalid_string_returns_none():
    assert _as_float("not_a_number") is None


def test_finite_none_is_false():
    assert _finite(None) is False


def test_finite_normal_value_is_true():
    assert _finite(1.5) is True


def test_finite_nan_and_inf_are_false():
    assert _finite(float("nan")) is False
    assert _finite(float("inf")) is False


# ---------------------------------------------------------------------------
# _bounds_sanity
# ---------------------------------------------------------------------------

def test_bounds_sanity_all_none_is_false():
    assert _bounds_sanity({"north": None, "south": None, "east": None, "west": None}) is False


def test_bounds_sanity_valid_bounds_is_true():
    bounds = {"north": 100.0, "south": 0.0, "east": 50.0, "west": 0.0}
    assert _bounds_sanity(bounds) is True


def test_bounds_sanity_north_less_than_south_is_false():
    bounds = {"north": 0.0, "south": 100.0, "east": 50.0, "west": 0.0}
    assert _bounds_sanity(bounds) is False


def test_bounds_sanity_east_less_than_west_is_false():
    bounds = {"north": 100.0, "south": 0.0, "east": 0.0, "west": 50.0}
    assert _bounds_sanity(bounds) is False


def test_bounds_sanity_partial_bounds_missing_values_is_false():
    bounds = {"north": 100.0, "south": None, "east": 50.0, "west": 0.0}
    assert _bounds_sanity(bounds) is False


def test_bounds_sanity_non_finite_value_is_false():
    bounds = {"north": float("nan"), "south": 0.0, "east": 50.0, "west": 0.0}
    assert _bounds_sanity(bounds) is False


# ---------------------------------------------------------------------------
# _parse_xodr_header
# ---------------------------------------------------------------------------

def test_parse_xodr_header_extracts_georef_and_bounds(tmp_path: Path):
    xodr = tmp_path / "a.xodr"
    _write_xodr(xodr)
    info = _parse_xodr_header(str(xodr))
    assert info["has_geoReference"] is True
    assert info["header_bounds"]["north"] == 1000.0
    assert len(info["xodr_sha256"]) == 64


def test_parse_xodr_header_no_georef_element(tmp_path: Path):
    xodr = tmp_path / "a.xodr"
    _write_xodr(xodr, georef=None)
    info = _parse_xodr_header(str(xodr))
    assert info["has_geoReference"] is False


def test_parse_xodr_header_extracts_offset(tmp_path: Path):
    xodr = tmp_path / "a.xodr"
    _write_xodr(xodr, offset=(832671.676, 5458671.104))
    info = _parse_xodr_header(str(xodr))
    assert info["header_offset"]["x"] == 832671.676
    assert info["header_offset"]["y"] == 5458671.104


def test_parse_xodr_header_no_header_element_at_all(tmp_path: Path):
    xodr = tmp_path / "a.xodr"
    ET.ElementTree(ET.Element("OpenDRIVE")).write(str(xodr), encoding="utf-8", xml_declaration=True)
    info = _parse_xodr_header(str(xodr))
    assert info["has_geoReference"] is False
    assert info["header_bounds"]["north"] is None


# ---------------------------------------------------------------------------
# build_report -- the actual gate logic
# ---------------------------------------------------------------------------

def test_build_report_missing_file_a(tmp_path: Path):
    b = tmp_path / "b.xodr"
    _write_xodr(b)
    report = build_report(str(tmp_path / "nope.xodr"), str(b))
    assert report["comparable"] is False
    assert "missing_file: a" in report["reason"]


def test_build_report_missing_file_b(tmp_path: Path):
    a = tmp_path / "a.xodr"
    _write_xodr(a)
    report = build_report(str(a), str(tmp_path / "nope.xodr"))
    assert report["comparable"] is False
    assert "missing_file: b" in report["reason"]


def test_build_report_both_missing_georef(tmp_path: Path):
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    _write_xodr(a, georef=None)
    _write_xodr(b, georef=None)
    report = build_report(str(a), str(b))
    assert report["comparable"] is False
    assert report["reason"] == "missing_georef: both"


def test_build_report_only_a_missing_georef(tmp_path: Path):
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    _write_xodr(a, georef=None)
    _write_xodr(b)
    report = build_report(str(a), str(b))
    assert report["comparable"] is False
    assert report["reason"] == "missing_georef: a"


def test_build_report_different_georef_refused(tmp_path: Path):
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    _write_xodr(a, georef="+proj=tmerc +lon_0=9 +datum=WGS84")
    _write_xodr(b, georef="+proj=utm +zone=32 +datum=WGS84")
    report = build_report(str(a), str(b))
    assert report["comparable"] is False
    assert report["reason"] == "different_georef"
    assert report["georef_match"] is False


def test_build_report_same_georef_and_sane_bounds_is_comparable(tmp_path: Path):
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    georef = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +datum=WGS84"
    _write_xodr(a, georef=georef)
    _write_xodr(b, georef=georef)
    report = build_report(str(a), str(b))
    assert report["comparable"] is True
    assert report["reason"] == "same_georef"
    assert report["georef_match"] is True
    assert report["bounds_sanity"] is True


def test_build_report_same_georef_but_invalid_bounds_refused(tmp_path: Path):
    a = tmp_path / "a.xodr"
    b = tmp_path / "b.xodr"
    georef = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +datum=WGS84"
    _write_xodr(a, georef=georef, north=None, south=None, east=None, west=None)
    _write_xodr(b, georef=georef)
    report = build_report(str(a), str(b))
    assert report["comparable"] is False
    assert report["reason"] == "invalid_bounds"


def test_build_report_malformed_xml_returns_parse_error(tmp_path: Path):
    a = tmp_path / "a.xodr"
    a.write_text("<OpenDRIVE><unclosed", encoding="utf-8")
    b = tmp_path / "b.xodr"
    _write_xodr(b)
    report = build_report(str(a), str(b))
    assert report["comparable"] is False
    assert "parse_error" in report["reason"]


def test_build_report_result_shape_always_has_expected_keys(tmp_path: Path):
    # even a total-failure report must have the stable shape callers rely on.
    report = build_report(str(tmp_path / "nope_a.xodr"), str(tmp_path / "nope_b.xodr"))
    assert set(report.keys()) >= {"comparable", "reason", "georef_match", "bounds_sanity", "a", "b"}
    assert json.dumps(report)  # must be JSON-serializable
