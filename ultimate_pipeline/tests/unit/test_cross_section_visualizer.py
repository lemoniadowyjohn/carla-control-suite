# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/visualization/cross_section_visualizer.py.

Zero prior test coverage. No bug found -- unlike the sibling
lane_overlay.py (fixed earlier this session for an XPath-depth
mismatch), this module correctly searches left/right lanes from
<laneSection> (sec.find("left")/sec.find("right")), matching real
OpenDRIVE structure.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from PIL import Image

from ultimate_pipeline.visualization.cross_section_visualizer import (
    CrossSectionVisualizer,
)


def _road_with_section(road_id: str, left=(), right=()) -> str:
    def _lane(lid, width, ltype="driving"):
        return f'<lane id="{lid}" type="{ltype}"><width sOffset="0" a="{width}" b="0" c="0" d="0"/></lane>'

    left_xml = "".join(_lane(i + 1, w, t) for i, (w, t) in enumerate(left))
    right_xml = "".join(_lane(-(i + 1), w, t) for i, (w, t) in enumerate(right))
    return (
        f'<road id="{road_id}" length="10">'
        f"<lanes><laneSection s=\"0\">"
        f"<left>{left_xml}</left><right>{right_xml}</right>"
        f"</laneSection></lanes>"
        f"</road>"
    )


# ---------------------------------------------------------------------------
# _sample_section
# ---------------------------------------------------------------------------


def test_sample_section_reads_left_and_right_widths_and_types():
    road = ET.fromstring(
        _road_with_section("1", left=[(3.5, "driving")], right=[(3.0, "driving"), (2.0, "sidewalk")])
    )
    left, right = CrossSectionVisualizer._sample_section(road)
    assert left == [(3.5, "driving")]
    assert right == [(3.0, "driving"), (2.0, "sidewalk")]


def test_sample_section_skips_lanes_without_width():
    road = ET.fromstring(
        '<road id="1"><lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving"/>'
        "</right></laneSection></lanes></road>"
    )
    left, right = CrossSectionVisualizer._sample_section(road)
    assert right == []


def test_sample_section_skips_non_positive_width():
    road = ET.fromstring(
        '<road id="1"><lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving"><width sOffset="0" a="0" b="0" c="0" d="0"/></lane>'
        "</right></laneSection></lanes></road>"
    )
    left, right = CrossSectionVisualizer._sample_section(road)
    assert right == []


def test_sample_section_uses_first_lanesection_by_s(tmp_path):
    road = ET.fromstring(
        '<road id="1"><lanes>'
        '<laneSection s="5"><right><lane id="-1" type="driving">'
        '<width sOffset="0" a="9.9" b="0" c="0" d="0"/></lane></right></laneSection>'
        '<laneSection s="0"><right><lane id="-1" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></right></laneSection>'
        "</lanes></road>"
    )
    left, right = CrossSectionVisualizer._sample_section(road)
    assert right == [(3.5, "driving")]  # the s=0 section, not s=5


def test_sample_section_no_lanes_element_returns_empty():
    road = ET.fromstring('<road id="1"/>')
    assert CrossSectionVisualizer._sample_section(road) == ([], [])


def test_sample_section_no_lanesections_returns_empty():
    road = ET.fromstring('<road id="1"><lanes></lanes></road>')
    assert CrossSectionVisualizer._sample_section(road) == ([], [])


# ---------------------------------------------------------------------------
# _lane_color
# ---------------------------------------------------------------------------


def test_lane_color_known_type_left_vs_right_differ():
    left_color = CrossSectionVisualizer._lane_color("driving", is_left=True)
    right_color = CrossSectionVisualizer._lane_color("driving", is_left=False)
    assert left_color != right_color


def test_lane_color_unknown_type_uses_fallback():
    assert CrossSectionVisualizer._lane_color("unknown_type", is_left=True) == (140, 140, 140)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_missing_xodr_prints_error(tmp_path, capsys):
    CrossSectionVisualizer.run(str(tmp_path / "missing.xodr"), str(tmp_path / "out.png"))
    assert "not found" in capsys.readouterr().out


def test_run_no_roads_prints_warning(tmp_path, capsys):
    xodr = tmp_path / "empty.xodr"
    xodr.write_text('<?xml version="1.0"?><OpenDRIVE></OpenDRIVE>', encoding="utf-8")
    CrossSectionVisualizer.run(str(xodr), str(tmp_path / "out.png"))
    assert "No roads" in capsys.readouterr().out


def test_run_writes_a_valid_png(tmp_path):
    xodr = tmp_path / "map.xodr"
    xodr.write_text(
        "<OpenDRIVE>" + _road_with_section("1", left=[(3.5, "driving")], right=[(3.0, "driving")]) + "</OpenDRIVE>",
        encoding="utf-8",
    )
    out_png = tmp_path / "cross_section.png"
    CrossSectionVisualizer.run(str(xodr), str(out_png))
    assert out_png.exists()
    img = Image.open(out_png)
    assert img.size[0] > 0 and img.size[1] > 0


def test_run_respects_max_roads_limit(tmp_path):
    roads_xml = "".join(
        _road_with_section(str(i), right=[(3.0, "driving")]) for i in range(10)
    )
    xodr = tmp_path / "map.xodr"
    xodr.write_text("<OpenDRIVE>" + roads_xml + "</OpenDRIVE>", encoding="utf-8")
    out_png = tmp_path / "out.png"
    CrossSectionVisualizer.run(str(xodr), str(out_png), max_roads=3)
    img = Image.open(out_png)
    # image height scales with number of rendered roads (row_h=18, pad_y=20*2)
    assert img.size[1] == 20 * 2 + 18 * 3
