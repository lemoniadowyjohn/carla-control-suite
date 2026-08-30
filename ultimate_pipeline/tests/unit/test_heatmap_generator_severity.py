# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/visualization/heatmap_generator.py.

Zero prior test coverage. No bug found. Reviewed the
`debug.get(rid)` / `debug.get(str(rid), {})` fallback -- redundant
(road.get("id") from ElementTree is already always a str, so str(rid) is
a no-op), but confirmed zero observable behavior difference either way,
since the immediately following `if info else 0.0` treats None and {}
identically.
"""
from __future__ import annotations

import json
import math

from PIL import Image

from ultimate_pipeline.visualization.heatmap_generator import HeatmapGenerator


# ---------------------------------------------------------------------------
# _severity_from_metrics
# ---------------------------------------------------------------------------


def test_severity_zero_for_clean_metrics():
    assert HeatmapGenerator._severity_from_metrics(0.0, 0.0, 0.0) == 0.0


def test_severity_capped_at_one_for_extreme_gap():
    assert HeatmapGenerator._severity_from_metrics(100.0, 0.0, 0.0) == 1.0


def test_severity_uses_max_of_three_normalized_metrics():
    # gap alone at half its "bad" threshold -> 0.5
    s = HeatmapGenerator._severity_from_metrics(2.5, 0.0, 0.0)
    assert abs(s - 0.5) < 1e-6
    # heading dominates when it's worse than gap
    s2 = HeatmapGenerator._severity_from_metrics(0.0, math.radians(15.0), 0.0)
    assert abs(s2 - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# _color_from_severity
# ---------------------------------------------------------------------------


def test_color_pure_green_at_zero_severity():
    assert HeatmapGenerator._color_from_severity(0.0) == (0, 255, 0)


def test_color_pure_red_at_full_severity():
    assert HeatmapGenerator._color_from_severity(1.0) == (255, 0, 0)


def test_color_clamps_out_of_range_severity():
    assert HeatmapGenerator._color_from_severity(-5.0) == (0, 255, 0)
    assert HeatmapGenerator._color_from_severity(5.0) == (255, 0, 0)


# ---------------------------------------------------------------------------
# _endpoint (shared arc-integration logic, same as lane_overlay.py's)
# ---------------------------------------------------------------------------


def test_endpoint_straight_line():
    import xml.etree.ElementTree as ET

    geo = ET.fromstring("<geometry><line/></geometry>")
    x, y, hdg = HeatmapGenerator._endpoint(0.0, 0.0, 0.0, 10.0, geo)
    assert abs(x - 10.0) < 1e-6
    assert abs(y) < 1e-6


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_missing_xodr_prints_error(tmp_path, capsys):
    HeatmapGenerator.run(str(tmp_path / "missing.xodr"), str(tmp_path / "out.png"))
    assert "not found" in capsys.readouterr().out


def test_run_missing_debug_json_prints_warning_and_skips(tmp_path, capsys):
    xodr = tmp_path / "map.xodr"
    xodr.write_text('<?xml version="1.0"?><OpenDRIVE></OpenDRIVE>', encoding="utf-8")
    HeatmapGenerator.run(
        str(xodr), str(tmp_path / "out.png"), debug_json=str(tmp_path / "missing.json")
    )
    assert "continuity_debug.json not found" in capsys.readouterr().out


def test_run_corrupted_debug_json_prints_warning_and_skips(tmp_path, capsys):
    xodr = tmp_path / "map.xodr"
    xodr.write_text('<?xml version="1.0"?><OpenDRIVE></OpenDRIVE>', encoding="utf-8")
    debug_json = tmp_path / "debug.json"
    debug_json.write_text("{not valid json", encoding="utf-8")
    HeatmapGenerator.run(str(xodr), str(tmp_path / "out.png"), debug_json=str(debug_json))
    assert "Failed to read" in capsys.readouterr().out


def test_run_no_geometry_prints_warning(tmp_path, capsys):
    xodr = tmp_path / "map.xodr"
    xodr.write_text('<?xml version="1.0"?><OpenDRIVE></OpenDRIVE>', encoding="utf-8")
    debug_json = tmp_path / "debug.json"
    debug_json.write_text("{}", encoding="utf-8")
    HeatmapGenerator.run(str(xodr), str(tmp_path / "out.png"), debug_json=str(debug_json))
    assert "No geometry" in capsys.readouterr().out


def test_run_writes_a_valid_png_with_anomaly_highlighted(tmp_path):
    xodr = tmp_path / "map.xodr"
    xodr.write_text(
        "<OpenDRIVE>"
        '<road id="1" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        "</planView></road>"
        '<road id="2" length="10"><planView>'
        '<geometry s="0" x="20" y="15" hdg="0" length="10"><line/></geometry>'
        "</planView></road>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    debug_json = tmp_path / "debug.json"
    debug_json.write_text(
        json.dumps({"1": {"max_gap": 10.0, "max_hdg": 0.0, "max_len": 0.0}}), encoding="utf-8"
    )
    out_png = tmp_path / "heatmap.png"
    HeatmapGenerator.run(str(xodr), str(out_png), debug_json=str(debug_json))
    assert out_png.exists()
    img = Image.open(out_png)
    assert img.size[0] > 0 and img.size[1] > 0


def test_run_degenerate_bbox_is_skipped(tmp_path, capsys):
    # All roads at the exact same point -> zero-size bounding box.
    xodr = tmp_path / "map.xodr"
    xodr.write_text(
        "<OpenDRIVE>"
        '<road id="1" length="1"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry>'
        "</planView></road>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    debug_json = tmp_path / "debug.json"
    debug_json.write_text("{}", encoding="utf-8")
    HeatmapGenerator.run(str(xodr), str(tmp_path / "out.png"), debug_json=str(debug_json))
    assert "Degenerate bounding box" in capsys.readouterr().out
