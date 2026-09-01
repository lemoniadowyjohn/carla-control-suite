# ultimate_pipeline/tools/xodr_coordinate_report.py -- zero prior test
# coverage. Live: invoked as a subprocess (`python -m
# ultimate_pipeline.tools.xodr_coordinate_report`) from both
# stage_11_12_sim_domain.py and stage_12_domain_gap.py to produce
# coord_manual.json/coord_auto.json "thesis evidence" for RQ1 domain-gap
# coordinate-frame diagnostics. The JSON is write-only (never read back by
# the pipeline), so bugs here affect evidence quality, not pipeline
# decisions.
#
# Two real issues found:
#  1. parse_georeference() returns (valid, params_complete, norm); `valid`
#     (whether the string is minimally usable, i.e. contains "+proj=") was
#     computed and silently discarded -- the report only exposed
#     geoReference_params_complete (all required keys present), so a
#     consumer couldn't distinguish "no usable geoReference at all" from
#     "valid but missing one optional param". Fixed: report now also
#     includes geoReference_valid.
#  2. float(x)/float(y) on a geometry's x/y attributes accepts the
#     strings "nan"/"inf"/"-inf" as valid floats. A non-finite point
#     reaching _bbox's min()/max() would silently produce an
#     iteration-order-dependent (i.e. wrong) bbox, since NaN comparisons
#     are always False. Fixed: non-finite points are now filtered out in
#     _extract_planview_points_stream, matching this session's established
#     math.isfinite() pattern for defeating this class of gate/computation
#     bug.
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.tools import xodr_coordinate_report as xcr


def _write_xodr(path: Path, *, geo_reference: str | None, geometries: list[tuple[str, str]]) -> None:
    geo_xml = f"<geoReference><![CDATA[{geo_reference}]]></geoReference>" if geo_reference else ""
    geoms_xml = "".join(
        f'<geometry s="0" x="{x}" y="{y}" hdg="0" length="10"><line/></geometry>'
        for x, y in geometries
    )
    xodr = f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4">
    {geo_xml}
  </header>
  <road name="R1" length="10.0" id="1" junction="-1">
    <planView>{geoms_xml}</planView>
  </road>
</OpenDRIVE>
"""
    path.write_text(xodr, encoding="utf-8")


def _run_main(monkeypatch, xodr: Path, out: Path) -> dict:
    monkeypatch.setattr(sys, "argv", ["xodr_coordinate_report.py", "--xodr", str(xodr), "--out", str(out)])
    rc = xcr.main()
    assert rc == 0
    return json.loads(out.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# _extract_planview_points_stream / _bbox
# ---------------------------------------------------------------------------

def test_extracts_geometry_start_points(tmp_path: Path):
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference=None, geometries=[("0", "0"), ("100", "50")])

    pts = xcr._extract_planview_points_stream(xodr)

    assert pts == [(0.0, 0.0), (100.0, 50.0)]


def test_filters_out_nonfinite_points(tmp_path: Path):
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference=None, geometries=[("0", "0"), ("nan", "5"), ("inf", "-inf"), ("100", "50")])

    pts = xcr._extract_planview_points_stream(xodr)

    assert pts == [(0.0, 0.0), (100.0, 50.0)]


def test_bbox_of_nonfinite_free_points_is_deterministic(tmp_path: Path):
    bb = xcr._bbox([(0.0, 0.0), (100.0, 50.0), (-20.0, 10.0)])
    assert bb == {"minx": -20.0, "maxx": 100.0, "miny": 0.0, "maxy": 50.0}


# ---------------------------------------------------------------------------
# main() end-to-end report content
# ---------------------------------------------------------------------------

def test_report_includes_geo_reference_valid_field(tmp_path: Path, monkeypatch):
    xodr = tmp_path / "in.xodr"
    _write_xodr(
        xodr,
        geo_reference="+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs",
        geometries=[("0", "0")],
    )
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["geoReference_valid"] is True
    assert report["geoReference_params_complete"] is True


def test_report_distinguishes_invalid_from_incomplete_georeference(tmp_path: Path, monkeypatch):
    # No "+proj=" at all -> geo_valid False AND params_complete False.
    # Before the fix, only params_complete was visible in the report, so
    # this case was indistinguishable from "valid but missing one param".
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference="garbage not a proj string", geometries=[("0", "0")])
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["geoReference_valid"] is False
    assert report["geoReference_params_complete"] is False


def test_report_valid_but_incomplete_georeference(tmp_path: Path, monkeypatch):
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference="+proj=tmerc +lat_0=0", geometries=[("0", "0")])
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["geoReference_valid"] is True
    assert report["geoReference_params_complete"] is False


def test_report_header_present_but_no_geo_reference_element(tmp_path: Path, monkeypatch):
    # <header> exists but has no <geoReference> child -- parse_georeference(None)
    # returns (False, False, ""), distinct from the "no <header> at all" case.
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference=None, geometries=[("0", "0")])
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["geoReference"] is None
    assert report["geoReference_valid"] is False
    assert report["geoReference_params_complete"] is False


def test_report_no_header_element_at_all(tmp_path: Path, monkeypatch):
    xodr = tmp_path / "in.xodr"
    xodr.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <road name="R1" length="10.0" id="1" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
  </road>
</OpenDRIVE>
""",
        encoding="utf-8",
    )
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["geoReference"] is None
    assert report["geoReference_valid"] is None
    assert report["geoReference_params_complete"] is None


def test_report_bbox_and_scale_hint_local_meters(tmp_path: Path, monkeypatch):
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference=None, geometries=[("0", "0"), ("500", "500")])
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["bbox"] == {"minx": 0.0, "maxx": 500.0, "miny": 0.0, "maxy": 500.0}
    assert report["coord_scale_hint"] == "local_meters"
    assert report["planView_geometry_points"] == 2


def test_report_scale_hint_large_global_for_projected_coords(tmp_path: Path, monkeypatch):
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference=None, geometries=[("690000", "5400000")])
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["coord_scale_hint"] == "large_global"


def test_report_bbox_ignores_nan_points_end_to_end(tmp_path: Path, monkeypatch):
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, geo_reference=None, geometries=[("0", "0"), ("nan", "nan"), ("10", "10")])
    out = tmp_path / "report.json"

    report = _run_main(monkeypatch, xodr, out)

    assert report["bbox"] == {"minx": 0.0, "maxx": 10.0, "miny": 0.0, "maxy": 10.0}
    assert report["planView_geometry_points"] == 2
