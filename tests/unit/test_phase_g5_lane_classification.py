from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.phase_g5_lane_classification import (
    _apply_reclassifications,
    audit_classification,
)


def _root(lane_sections: str) -> ET.Element:
    return ET.fromstring(
        f"""<OpenDRIVE><road id="1" length="20">
        <lanes>{lane_sections}</lanes></road></OpenDRIVE>"""
    )


def _lane(lane_id: int, lane_type: str) -> str:
    return (
        f'<lane id="{lane_id}" type="{lane_type}">'
        '<width sOffset="0" a="3.5"/></lane>'
    )


def test_outermost_walk_lane_does_not_compare_against_opposite_side_driving_lane():
    root = _root(
        f'<laneSection s="0"><left>{_lane(1, "sidewalk")}</left>'
        f'<right>{_lane(-1, "driving")}{_lane(-2, "driving")}</right>'
        '</laneSection>'
    )

    report = audit_classification(root)

    assert report["walk_lane_not_outermost"] == []


def test_walk_lane_inside_driving_lane_on_its_own_side_is_reported():
    root = _root(
        f'<laneSection s="0"><right>{_lane(-1, "sidewalk")}'
        f'{_lane(-2, "driving")}</right></laneSection>'
    )

    report = audit_classification(root)

    assert report["walk_lane_not_outermost"] == [
        {"road": "1", "lane_section_s": "0", "walk_lane": -1, "driving_lane": "-2"}
    ]


def test_reclassification_is_limited_to_the_qualified_lane_section():
    root = _root(
        f'<laneSection s="0"><right>{_lane(-1, "restricted")}</right></laneSection>'
        f'<laneSection s="10"><right>{_lane(-1, "restricted")}</right></laneSection>'
    )

    changed = _apply_reclassifications(root, [("1", "10", -1)])
    sections = root.findall("road/lanes/laneSection")

    assert changed == 1
    assert sections[0].find("right/lane").get("type") == "restricted"
    assert sections[1].find("right/lane").get("type") == "driving"
