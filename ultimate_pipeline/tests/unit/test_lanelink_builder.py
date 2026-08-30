# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/lanes/lanelink_builder.py.

Live: LaneLinkBuilder rebuilds <laneLink> elements inside <junction>
<connection> elements -- directly in-scope for this branch
(fix/post-audit-phase-e-junctions-roundabouts). Zero prior test coverage.
Reviewed carefully for the defect classes found elsewhere this session
(silently-defeated checks, ElementTree truthiness gotchas in the
`in_right.get(from_id) or in_left.get(from_id)` fallback) -- no bug found:
the fallback's only failure mode (a real-but-childless Element being
treated as falsy) still gets caught by the very next `findall("width")`
check either way, since a childless lane also has zero <width> children.
"""
from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET

from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder


def _lane_xml(lane_id: int, lane_type: str = "driving", with_width: bool = True) -> str:
    width = '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>' if with_width else ""
    return f'<lane id="{lane_id}" type="{lane_type}">{width}</lane>'


def _road(
    road_id: str,
    junction: str,
    right_lanes: str = "",
    left_lanes: str = "",
) -> str:
    return (
        f'<road id="{road_id}" length="10" junction="{junction}">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        f'<lanes><laneSection s="0">'
        f"<left>{left_lanes}</left>"
        f'<center><lane id="0" type="driving"/></center>'
        f"<right>{right_lanes}</right>"
        f"</laneSection></lanes>"
        f"</road>"
    )


def _junction(junction_id: str, incoming: str, connecting: str, contact_point: str = "start") -> str:
    return (
        f'<junction id="{junction_id}">'
        f'<connection id="0" incomingRoad="{incoming}" connectingRoad="{connecting}" '
        f'contactPoint="{contact_point}"/>'
        f"</junction>"
    )


def _parse(*parts: str) -> ET.Element:
    return ET.fromstring("<OpenDRIVE>" + "".join(parts) + "</OpenDRIVE>")


def test_links_matching_right_side_driving_lanes():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1)),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2", contact_point="start"),
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)

    conn = root.find(".//junction/connection")
    links = conn.findall("laneLink")
    assert len(links) == 1
    assert links[0].attrib == {"from": "-1", "to": "-1"}


def test_links_matching_left_side_driving_lanes():
    root = _parse(
        _road("1", "-1", left_lanes=_lane_xml(1)),
        _road("2", "5", left_lanes=_lane_xml(1)),
        _junction("5", "1", "2", contact_point="start"),
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    assert len(links) == 1
    assert links[0].attrib == {"from": "1", "to": "1"}


def test_non_driving_lane_type_is_excluded():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1, lane_type="sidewalk")),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2"),
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    assert links == []


def test_lane_missing_width_is_excluded():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1, with_width=False)),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2"),
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    assert links == []


def test_invalid_road_reference_is_skipped_without_crashing():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "999"),  # road 999 does not exist
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    assert links == []


def test_existing_lanelinks_are_wiped_before_rebuild():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1)),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2"),
    )
    conn = root.find(".//junction/connection")
    # Pre-seed a stale/bogus laneLink that should not survive the rebuild.
    ET.SubElement(conn, "laneLink", {"from": "-99", "to": "-99"})
    assert len(conn.findall("laneLink")) == 1

    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)

    links = conn.findall("laneLink")
    assert len(links) == 1
    assert links[0].attrib == {"from": "-1", "to": "-1"}  # stale entry gone


def test_contact_point_end_uses_connecting_roads_last_lanesection():
    right_lane_a = _lane_xml(-1)
    right_lane_b = _lane_xml(-2)
    connecting_road = (
        f'<road id="2" length="10" junction="5">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        f'<lanes>'
        f'<laneSection s="0"><right>{right_lane_a}</right></laneSection>'
        f'<laneSection s="5"><right>{right_lane_b}</right></laneSection>'
        f'</lanes></road>'
    )
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-2)),
        connecting_road,
        _junction("5", "1", "2", contact_point="end"),
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    # contactPoint="end" -> uses the connecting road's LAST laneSection
    # (lane id -2, not the first section's -1).
    assert len(links) == 1
    assert links[0].attrib == {"from": "-2", "to": "-2"}


def test_multiple_lanes_pair_inner_first():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction("5", "1", "2"),
    )
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    pairs = {(l.attrib["from"], l.attrib["to"]) for l in links}
    assert pairs == {("-1", "-1"), ("-2", "-2")}


def test_regenerate_wrapper_delegates_to_regenerate_lane_links():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1)),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2"),
    )
    LaneLinkBuilder.regenerate(root, verbose=False)
    links = root.find(".//junction/connection").findall("laneLink")
    assert len(links) == 1


def test_sanitize_junction_lane_links_stub_returns_ok_status():
    root = _parse()
    result = LaneLinkBuilder.sanitize_junction_lane_links(root, label="test")
    assert result["status"] == "ok"
    assert "summary_metrics" in result


def test_no_junctions_produces_no_links_and_does_not_crash():
    root = _parse(_road("1", "-1", right_lanes=_lane_xml(-1)))
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)  # must not raise


def test_does_not_test_element_truth_value():
    # ElementTree's bool(Element) (len(elem) > 0) is deprecated and will
    # become a hard TypeError in a future Python version -- this function
    # must use explicit `is None` checks, not `if not element` / `a or b`,
    # for any variable that may hold a real (possibly childless) Element.
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1)),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2"),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
