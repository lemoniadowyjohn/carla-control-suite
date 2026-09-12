from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.lanes.turn_restriction_audit import (
    audit_lane_link_turn_classification,
)


def _lane(lane_id: int) -> str:
    return (
        f'<lane id="{lane_id}" type="driving">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane>'
    )


def _road(
    road_id: str,
    x: float,
    y: float,
    heading: float,
    primitive: str,
    lanes: str,
) -> str:
    return (
        f'<road id="{road_id}" length="10" junction="-1">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{heading}" length="10">'
        f"{primitive}</geometry></planView><lanes><laneSection s=\"0\">"
        f'<left/><center><lane id="0" type="none"/></center><right>{lanes}</right>'
        "</laneSection></lanes></road>"
    )


def _root() -> ET.Element:
    return ET.fromstring(
        "<OpenDRIVE>"
        + _road("1", 0, 0, 0, "<line/>", _lane(-1) + _lane(-2))
        + _road(
            "2",
            10,
            0,
            0,
            '<arc curvature="0.15707963267948966"/>',
            _lane(-1) + _lane(-2),
        )
        + _road(
            "3",
            10,
            0,
            0,
            '<arc curvature="-0.15707963267948966"/>',
            _lane(-1) + _lane(-2),
        )
        + '<junction id="9">'
        '<connection id="left" incomingRoad="1" connectingRoad="2" contactPoint="start">'
        '<laneLink from="-1" to="-1"/></connection>'
        '<connection id="right" incomingRoad="1" connectingRoad="3" contactPoint="start">'
        '<laneLink from="-2" to="-2"/></connection>'
        "</junction></OpenDRIVE>"
    )


def _association(pattern: str, *, orientation: str = "forward") -> dict:
    return {
        "class": "HIGH",
        "osm_way_id": "w-1",
        "osm_direction": orientation,
        "metadata": {"turn:lanes:forward": pattern},
    }


def test_direct_turn_metadata_agrees_with_left_and_right_connectors() -> None:
    result = audit_lane_link_turn_classification(
        _root(), {"1": _association("left|right")}
    )

    assert result["status"] == "PASS"
    assert result["summary_metrics"] == {
        "multi_exit_connections": 2,
        "lane_links_checked": 2,
        "agree": 2,
        "disagree": 0,
        "no_osm_turn_data": 0,
        "incomplete": 0,
    }
    assert {row["geometry_turn"] for row in result["connections"]} == {"left", "right"}


def test_turn_metadata_reports_conflicting_connector_without_mutating_xml() -> None:
    root = _root()
    root.find('.//connection[@id="left"]/laneLink').set("from", "-2")
    root.find('.//connection[@id="right"]/laneLink').set("from", "-1")
    before = ET.tostring(root)

    result = audit_lane_link_turn_classification(root, {"1": _association("left|right")})

    assert result["status"] == "FAIL"
    assert result["summary_metrics"]["disagree"] == 2
    assert ET.tostring(root) == before


def test_name_only_or_unoriented_metadata_is_rejected_fail_closed() -> None:
    result = audit_lane_link_turn_classification(
        _root(),
        {"1": {"class": "HIGH", "metadata": {"turn:lanes:forward": "left|right"}}},
    )

    assert result["status"] == "INCOMPLETE"
    assert result["summary_metrics"]["no_osm_turn_data"] == 2
    assert {row["reason"] for row in result["connections"]} == {
        "missing_high_confidence_oriented_correspondence"
    }


def test_reverse_osm_orientation_selects_backward_directional_pattern() -> None:
    root = _root()
    association = {
        "class": "EXACT",
        "osm_way_id": "w-1",
        "osm_direction": "reverse",
        "metadata": {"turn:lanes:backward": "left|right"},
    }

    result = audit_lane_link_turn_classification(root, {"1": association})

    assert result["status"] == "PASS"
    assert result["summary_metrics"]["agree"] == 2


def test_connector_turn_angle_is_reported() -> None:
    result = audit_lane_link_turn_classification(
        _root(), {"1": _association("left|right")}
    )

    angles = {
        row["geometry_turn"]: row["geometry_turn_angle_deg"]
        for row in result["connections"]
    }
    assert math.isclose(angles["left"], 90.0, abs_tol=1e-9)
    assert math.isclose(angles["right"], -90.0, abs_tol=1e-9)
