"""ultimate_pipeline/tools/xodr_structural_summary.py -- deterministic, stdlib-only structural
summary (road/junction/lane counts, total length, geoReference info, content hash) for an XODR
file. Wired into run_full_domain_gap.py and compute_missing_run11_metrics.py, feeding real
thesis evidence. Found via an expanded orphaned-.pyc sweep of the top-level tests/ directory
(the original tests/test_xodr_structural_summary.py no longer exists on this branch).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tools.xodr_structural_summary import (
    _header_bounds,
    _header_offset,
    _normalize_bytes,
    _parse_float,
    _stable_float,
    summarize_xodr,
)


# ---------------------------------------------------------------------------
# _normalize_bytes
# ---------------------------------------------------------------------------

def test_normalize_bytes_crlf_to_lf():
    assert _normalize_bytes(b"line1\r\nline2\r\n") == b"line1\nline2\n"


def test_normalize_bytes_bare_cr_to_lf():
    assert _normalize_bytes(b"line1\rline2\r") == b"line1\nline2\n"


def test_normalize_bytes_already_lf_unchanged():
    assert _normalize_bytes(b"line1\nline2\n") == b"line1\nline2\n"


# ---------------------------------------------------------------------------
# _parse_float / _stable_float
# ---------------------------------------------------------------------------

def test_parse_float_none_returns_none():
    assert _parse_float(None) is None


def test_parse_float_valid_string():
    assert _parse_float("3.14") == 3.14


def test_parse_float_invalid_string_returns_none():
    assert _parse_float("not_a_number") is None


def test_parse_float_rejects_non_finite_values():
    assert _parse_float("nan") is None
    assert _parse_float("inf") is None


def test_stable_float_clamps_to_six_decimals():
    assert _stable_float(1.0 / 3.0) == 0.333333


def test_stable_float_none_passthrough():
    assert _stable_float(None) is None


# ---------------------------------------------------------------------------
# _header_bounds / _header_offset
# ---------------------------------------------------------------------------

def test_header_bounds_none_header_returns_all_none():
    bounds = _header_bounds(None)
    assert bounds == {"north": None, "south": None, "east": None, "west": None}


def test_header_bounds_extracts_and_rounds():
    header = ET.Element("header", north="100.123456789", south="0.0", east="50.0", west="0.0")
    bounds = _header_bounds(header)
    assert bounds["north"] == 100.123457


def test_header_offset_none_header_returns_all_none():
    offset = _header_offset(None)
    assert offset == {"x": None, "y": None, "z": None, "hdg": None}


def test_header_offset_extracts_values():
    header = ET.Element("header")
    ET.SubElement(header, "offset", x="832671.676", y="5458671.104", z="0.0", hdg="0.0")
    offset = _header_offset(header)
    assert offset["x"] == 832671.676
    assert offset["y"] == 5458671.104


def test_header_offset_no_offset_element_returns_all_none():
    header = ET.Element("header")
    offset = _header_offset(header)
    assert offset == {"x": None, "y": None, "z": None, "hdg": None}


# ---------------------------------------------------------------------------
# summarize_xodr -- end-to-end
# ---------------------------------------------------------------------------

def _write_xodr(path: Path, xml_bytes: bytes) -> None:
    path.write_bytes(xml_bytes)


def test_summarize_xodr_counts_roads_and_junctions(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, (
        b"<OpenDRIVE>"
        b'<road id="1" length="100.0" junction="-1"/>'
        b'<road id="2" length="50.0" junction="5"/>'
        b"</OpenDRIVE>"
    ))
    summary = summarize_xodr(xodr)
    assert summary["road_count"] == 2
    assert summary["junction_count"] == 1  # only road "2" (junction != "-1")
    assert summary["total_road_length_m"] == 150.0


def test_summarize_xodr_lane_count_excludes_center_lane(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, (
        b"<OpenDRIVE><road id=\"1\" length=\"10.0\" junction=\"-1\">"
        b'<lanes><laneSection>'
        b'<center><lane id="0" type="none"/></center>'
        b'<right><lane id="-1" type="driving"/></right>'
        b"</laneSection></lanes></road></OpenDRIVE>"
    ))
    summary = summarize_xodr(xodr)
    assert summary["lane_section_count"] == 1
    assert summary["lane_count_total"] == 1  # center lane (id=0) excluded


def test_summarize_xodr_georeference_extracted(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    georef = b"+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +datum=WGS84"
    _write_xodr(xodr, (
        b'<OpenDRIVE><header north="100" south="0" east="50" west="0">'
        b"<geoReference>" + georef + b"</geoReference>"
        b"</header></OpenDRIVE>"
    ))
    summary = summarize_xodr(xodr)
    assert summary["has_geoReference"] is True
    assert summary["geoReference_norm"] is not None


def test_summarize_xodr_no_georeference(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, b"<OpenDRIVE><header/></OpenDRIVE>")
    summary = summarize_xodr(xodr)
    assert summary["has_geoReference"] is False
    assert summary["geoReference_norm"] is None


def test_summarize_xodr_sha256_is_stable_across_line_ending_variants(tmp_path: Path):
    xodr_lf = tmp_path / "lf.xodr"
    xodr_crlf = tmp_path / "crlf.xodr"
    content = b'<OpenDRIVE>\n<road id="1" length="10.0" junction="-1"/>\n</OpenDRIVE>\n'
    _write_xodr(xodr_lf, content)
    _write_xodr(xodr_crlf, content.replace(b"\n", b"\r\n"))

    summary_lf = summarize_xodr(xodr_lf)
    summary_crlf = summarize_xodr(xodr_crlf)

    assert summary_lf["xodr_sha256"] == summary_crlf["xodr_sha256"]


def test_summarize_xodr_missing_length_attribute_does_not_crash(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, b'<OpenDRIVE><road id="1" junction="-1"/></OpenDRIVE>')
    summary = summarize_xodr(xodr)
    assert summary["total_road_length_m"] == 0.0


def test_summarize_xodr_no_roads_returns_zero_counts(tmp_path: Path):
    xodr = tmp_path / "map.xodr"
    _write_xodr(xodr, b"<OpenDRIVE/>")
    summary = summarize_xodr(xodr)
    assert summary["road_count"] == 0
    assert summary["junction_count"] == 0
    assert summary["total_road_length_m"] == 0.0
