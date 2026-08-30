# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/visualization/lane_overlay.py.

Zero prior test coverage. Reviewed the geometry/polyline construction in
run() carefully (initially looked like it might reprocess the first
geometry segment redundantly) -- confirmed correct: pts starts with g0's
start point, then the loop (starting at g0 again) computes each
geometry's END point in sequence, producing [g0_start, g0_end, g1_end,
...]. No bug found. PIL-based (not matplotlib), no headless-backend
concerns.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from PIL import Image

from ultimate_pipeline.visualization.lane_overlay import LaneOverlay


def _road_xml(road_id: str, x: float, right_lanes=(), left_lanes=()) -> str:
    def _lane(lid, ltype="driving"):
        return f'<lane id="{lid}" type="{ltype}"/>'

    right_xml = "".join(_lane(i) for i in right_lanes)
    left_xml = "".join(_lane(i) for i in left_lanes)
    return (
        f'<road id="{road_id}" length="10">'
        f'<planView><geometry s="0" x="{x}" y="0" hdg="0" length="10"><line/></geometry></planView>'
        f"<lanes><laneSection s=\"0\">"
        f"<left>{left_xml}</left><right>{right_xml}</right>"
        f"</laneSection></lanes>"
        f"</road>"
    )


# ---------------------------------------------------------------------------
# _count_driving_lanes
# ---------------------------------------------------------------------------


def test_count_driving_lanes_sums_left_and_right():
    root = ET.fromstring(
        "<OpenDRIVE>" + _road_xml("1", 0, right_lanes=(-1, -2), left_lanes=(1,)) + "</OpenDRIVE>"
    )
    road = root.find("road")
    assert LaneOverlay._count_driving_lanes(road) == 3


def test_count_driving_lanes_excludes_non_driving_types():
    road = ET.fromstring(
        '<road id="1"><lanes><laneSection s="0">'
        '<right><lane id="-1" type="sidewalk"/><lane id="-2" type="driving"/></right>'
        "</laneSection></lanes></road>"
    )
    assert LaneOverlay._count_driving_lanes(road) == 1


def test_count_driving_lanes_no_lanes_element_returns_zero():
    road = ET.fromstring('<road id="1"/>')
    assert LaneOverlay._count_driving_lanes(road) == 0


# ---------------------------------------------------------------------------
# _color_for_lane_count
# ---------------------------------------------------------------------------


def test_color_thresholds():
    assert LaneOverlay._color_for_lane_count(0) == (90, 90, 90)
    assert LaneOverlay._color_for_lane_count(2) == (80, 160, 255)
    assert LaneOverlay._color_for_lane_count(4) == (80, 220, 120)
    assert LaneOverlay._color_for_lane_count(6) == (255, 220, 80)
    assert LaneOverlay._color_for_lane_count(10) == (255, 80, 80)


# ---------------------------------------------------------------------------
# _endpoint
# ---------------------------------------------------------------------------


def test_endpoint_straight_line_no_arc():
    geo = ET.fromstring('<geometry><line/></geometry>')
    x, y, hdg = LaneOverlay._endpoint(0.0, 0.0, 0.0, 10.0, geo)
    assert abs(x - 10.0) < 1e-6
    assert abs(y - 0.0) < 1e-6
    assert hdg == 0.0


def test_endpoint_arc_curves_away_from_straight_line():
    geo = ET.fromstring('<geometry><arc curvature="0.1"/></geometry>')
    x, y, hdg = LaneOverlay._endpoint(0.0, 0.0, 0.0, 10.0, geo)
    straight_x, straight_y, _ = LaneOverlay._endpoint(
        0.0, 0.0, 0.0, 10.0, ET.fromstring("<geometry><line/></geometry>")
    )
    assert (x, y) != (straight_x, straight_y)
    assert hdg != 0.0


def test_endpoint_negligible_curvature_treated_as_straight():
    geo = ET.fromstring('<geometry><arc curvature="1e-12"/></geometry>')
    x, y, hdg = LaneOverlay._endpoint(0.0, 0.0, 0.0, 10.0, geo)
    assert abs(x - 10.0) < 1e-6
    assert abs(y - 0.0) < 1e-6


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_missing_xodr_prints_error_and_returns(tmp_path, capsys):
    LaneOverlay.run(str(tmp_path / "missing.xodr"), str(tmp_path / "out.png"))
    assert "not found" in capsys.readouterr().out
    assert not (tmp_path / "out.png").exists()


def test_run_no_geometry_skips_without_crashing(tmp_path, capsys):
    xodr = tmp_path / "empty.xodr"
    xodr.write_text('<?xml version="1.0"?><OpenDRIVE></OpenDRIVE>', encoding="utf-8")
    LaneOverlay.run(str(xodr), str(tmp_path / "out.png"))
    assert "No geometry" in capsys.readouterr().out
    assert not (tmp_path / "out.png").exists()


def test_run_writes_a_valid_png(tmp_path):
    xodr = tmp_path / "map.xodr"
    xodr.write_text(
        "<OpenDRIVE>"
        + _road_xml("1", 0, right_lanes=(-1, -2))
        + _road_xml("2", 20, right_lanes=(-1,))
        + "</OpenDRIVE>",
        encoding="utf-8",
    )
    out_png = tmp_path / "overlay.png"
    LaneOverlay.run(str(xodr), str(out_png))

    assert out_png.exists()
    img = Image.open(out_png)
    assert img.size[0] > 0 and img.size[1] > 0
