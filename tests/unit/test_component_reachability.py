# Component-reachability gate (live-CARLA probe finding): lanes on road
# components disconnected from the main drivable network can never be
# autopilot-routed, so spawn points on them produce dead runs. The checker
# must report connected components of the lane topology, and the acceptance
# gate must hard-fail (opt-in) when >5% of lanes sit off the largest
# component.
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.map_acceptance import (
    build_map_acceptance,
    component_reachability_summary,
)


def _xodr(roads_xml: str) -> ET.Element:
    return ET.fromstring(
        "<OpenDRIVE>" + roads_xml + "</OpenDRIVE>"
    )


def _road(rid: str, lanes: list[tuple[str, str]], lane_type: str = "driving") -> str:
    lane_xml = "".join(
        f'<lane id="{lid}" type="{lane_type}"><link>{link_xml}</link></lane>'
        for lid, link_xml in lanes
    )
    return f'<road id="{rid}"><lanes><laneSection>{lane_xml}</laneSection></lanes></road>'


def _two_lane_road(rid: str, link_xml: str = "") -> str:
    return _road(rid, [("1", link_xml), ("-1", "")])


def test_two_disconnected_roads_report_isolated_lanes() -> None:
    # Each lane is an independent drivable component: lane 1 and lane -1 of
    # the same road only join the main network through real links, so with no
    # links at all every lane is its own isolated component.
    root = _xodr(_two_lane_road("0") + _two_lane_road("1"))
    rep = component_reachability_summary(root)
    assert rep is not None
    assert rep["lane_count"] == 4
    assert rep["component_count"] == 4
    assert rep["largest_component_lane_count"] == 1
    assert rep["largest_component_fraction"] == 0.25
    assert rep["isolated_lane_component_count"] == 4


def test_cross_road_link_connects_components() -> None:
    # road0 lane1 -> road1 lane1 joins those two lanes into one component;
    # the two -1 lanes stay isolated.
    link = '<successor id="1" elementType="road" elementId="1" contactPoint="start"/>'
    root = _xodr(_two_lane_road("0", link_xml=link) + _two_lane_road("1"))
    rep = component_reachability_summary(root)
    assert rep is not None
    assert rep["component_count"] == 3
    assert rep["largest_component_lane_count"] == 2
    assert rep["largest_component_fraction"] == 0.5
    assert rep["unmatched_cross_links"] == 0


def test_within_road_successor_links_sections() -> None:
    # Two lane sections on one road, linked by successor id (same lane id).
    sec0 = '<laneSection><lane id="1" type="driving"><link><successor id="1"/></link></lane></laneSection>'
    sec1 = '<laneSection><lane id="1" type="driving"><link><predecessor id="1"/></link></lane></laneSection>'
    root = ET.fromstring(
        f'<OpenDRIVE><road id="0"><lanes>{sec0}{sec1}</lanes></road></OpenDRIVE>'
    )
    rep = component_reachability_summary(root)
    assert rep is not None
    assert rep["component_count"] == 1
    assert rep["largest_component_fraction"] == 1.0


def test_broken_cross_road_link_is_reported_not_crashed() -> None:
    # Link to a nonexistent road: must not crash, must count as unmatched.
    link = '<successor id="1" elementType="road" elementId="999" contactPoint="start"/>'
    root = _xodr(_road("0", [("1", link)]))
    rep = component_reachability_summary(root)
    assert rep is not None
    assert rep["unmatched_cross_links"] == 1
    assert rep["component_count"] == 1


def test_gate_metric_always_reported_without_opt_in(tmp_path) -> None:
    xodr = tmp_path / "fragmented.xodr"
    xodr.write_text(
        "<OpenDRIVE>" + _two_lane_road("0") + _two_lane_road("1") + "</OpenDRIVE>",
        encoding="utf-8",
    )
    acceptance = build_map_acceptance({}, final_xodr_path=str(xodr))
    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["largest_component_fraction"] == 0.25
    assert any(w["gate"] == "component_reachability" for w in acceptance["soft_warnings"])


def test_gate_hard_fails_on_fragmented_when_opted_in(tmp_path) -> None:
    xodr = tmp_path / "fragmented.xodr"
    xodr.write_text(
        "<OpenDRIVE>" + _two_lane_road("0") + _two_lane_road("1") + "</OpenDRIVE>",
        encoding="utf-8",
    )
    acceptance = build_map_acceptance(
        {},
        final_xodr_path=str(xodr),
        require_component_reachability=True,
    )
    assert acceptance["valid_for_experiments"] is False
    assert "component_reachability" in acceptance["failed_gates"]


def test_gate_passes_connected_when_opted_in(tmp_path) -> None:
    # Both lanes of both roads joined into one component: two single-lane
    # roads linked in both directions (road0 lane1 <-> road1 lane1).
    fwd = '<successor id="1" elementType="road" elementId="1" contactPoint="start"/>'
    rev = '<predecessor id="1" elementType="road" elementId="0" contactPoint="end"/>'
    xodr = tmp_path / "connected.xodr"
    xodr.write_text(
        "<OpenDRIVE>"
        + _road("0", [("1", fwd)])
        + _road("1", [("1", rev)])
        + "</OpenDRIVE>",
        encoding="utf-8",
    )
    acceptance = build_map_acceptance(
        {},
        final_xodr_path=str(xodr),
        require_component_reachability=True,
    )
    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["largest_component_fraction"] == 1.0


def test_non_driving_lanes_are_excluded() -> None:
    # A sidewalk lane is not a drivable-network member: it must not count
    # toward lane_count, components, or isolated components.
    root = _xodr(
        _road("0", [("1", ""), ("-1", "")])
        + _road("1", [("1", ""), ("-1", "")], lane_type="sidewalk")
    )
    rep = component_reachability_summary(root)
    assert rep is not None
    assert rep["lane_count"] == 2
    assert rep["component_count"] == 2
    assert rep["isolated_lane_component_count"] == 2


def test_junction_connection_unions_lanes() -> None:
    # road0 (incoming) -> junction -> road2 (connecting) via laneLink from=-1
    # to=-1. The connection's contactPoint says "start" but road0 attaches at
    # its end (fallback must resolve it).
    junction_xml = (
        '<junction id="7"><connection id="0" incomingRoad="0" '
        'connectingRoad="2" contactPoint="start">'
        '<laneLink from="-1" to="-1"/></connection></junction>'
    )
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("0", [("1", ""), ("-1", "")])
        + _road("2", [("1", ""), ("-1", "")])
        + junction_xml
        + "</OpenDRIVE>"
    )
    rep = component_reachability_summary(root)
    assert rep is not None
    assert rep["component_count"] == 3
    assert rep["largest_component_lane_count"] == 2
    assert rep["largest_component_fraction"] == 0.5
