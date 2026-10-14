# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/topology/junction_connector_tangent_fit.py
(CARLA-CLOSURE-17, GAP026 severe-angle connector closure).

The 8 required fixtures:
  1. ~0.1m failing stub
  2. heading flip
  3. near-coincident endpoints
  4. normal connector
  5. lane-count reduction connector (laneLinks must be preserved)
  6. contactPoint=start
  7. contactPoint=end
  8. previously passing control (must NOT be touched)

Every angle/dist assertion replicates the gap026 oracle formula exactly using
the same geometry-kernel functions the oracle itself imports
(``pose_at_s`` / ``endpoint`` from ultimate_pipeline.geometry.
opendrive_geometry_kernel): reference-line headings, contactPoint start -> no
flip, end -> +pi. laneLinks are asserted byte-identical in every fitted case.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s
from ultimate_pipeline.topology.junction_connector_tangent_fit import (
    fit_junction_connector_tangents,
)

_ANGLE_THRESHOLD_DEG = 12.0


def _lane_xml(lane_id: int, width_a: float = 3.0, lane_type: str = "driving") -> str:
    return (
        f'<lane id="{lane_id}" type="{lane_type}">'
        f'<width sOffset="0" a="{width_a}" b="0" c="0" d="0"/>'
        f"</lane>"
    )


def _right(count: int) -> str:
    return "".join(_lane_xml(-i) for i in range(1, count + 1))


def _line_road(
    road_id: str,
    junction: str,
    *,
    x: float,
    y: float,
    hdg: float,
    length: float,
    right_lanes: str,
) -> str:
    return (
        f'<road id="{road_id}" length="{length}" junction="{junction}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{hdg}" length="{length}">'
        f"<line/></geometry></planView>"
        f'<lanes><laneSection s="0">'
        f"<left></left>"
        f'<center><lane id="0" type="driving"/></center>'
        f"<right>{right_lanes}</right>"
        f"</laneSection></lanes>"
        f"</road>"
    )


def _junction(
    junction_id: str,
    incoming: str,
    connecting: str,
    contact_point: str = "start",
    lane_links: str = '<laneLink from="-1" to="-1"/>',
) -> str:
    return (
        f'<junction id="{junction_id}">'
        f'<connection id="0" incomingRoad="{incoming}" connectingRoad="{connecting}" '
        f'contactPoint="{contact_point}">{lane_links}</connection>'
        f"</junction>"
    )


def _parse(*parts: str) -> ET.Element:
    return ET.fromstring("<OpenDRIVE>" + "".join(parts) + "</OpenDRIVE>")


def _geoms(road: ET.Element) -> list[ET.Element]:
    plan = road.find("./planView")
    assert plan is not None, "road has no planView"
    geoms = list(plan.findall("./geometry"))
    geoms.sort(key=lambda g: float(g.get("s", 0.0)))
    return geoms


def _roads(root: ET.Element) -> dict[str, ET.Element]:
    return {str(r.get("id")): r for r in root.findall("./road")}


def _connection(root: ET.Element) -> ET.Element:
    conn = root.find("./junction/connection")
    assert conn is not None, "no connection in fixture"
    return conn


def _angle_deg_and_gap(root: ET.Element) -> tuple[float, float]:
    """gap026 oracle connection angle (deg) and contact gap (m), verbatim."""
    roads = _roads(root)
    conn = _connection(root)
    inc = roads[str(conn.get("incomingRoad"))]
    con = roads[str(conn.get("connectingRoad"))]
    at_start = str(conn.get("contactPoint", "start")) != "end"

    src = endpoint(_geoms(inc)[-1])
    cgeoms = _geoms(con)
    contact = pose_at_s(cgeoms[0], 0.0) if at_start else endpoint(cgeoms[-1])

    heading_target = contact.heading + (0.0 if at_start else math.pi)
    ang = (src.heading - heading_target + math.pi) % (2.0 * math.pi) - math.pi
    dist = math.hypot(src.x - contact.x, src.y - contact.y)
    return math.degrees(abs(ang)), dist


def _lane_links_xml(root: ET.Element) -> str:
    return ET.tostring(_connection(root), encoding="unicode")


def _incoming_and_connector(
    connecting_hdg: float,
    *,
    connecting_length: float = 10.0,
    connecting_x: float = 100.0,
    connecting_y: float = 0.0,
    incoming_right: str | None = None,
    connecting_right: str | None = None,
    contact_point: str = "start",
    lane_links: str = '<laneLink from="-1" to="-1"/>',
) -> ET.Element:
    """incoming: length 100 at origin heading 0 -> source pose (100, 0, 0)."""
    return _parse(
        _line_road(
            "1",
            "-1",
            x=0.0,
            y=0.0,
            hdg=0.0,
            length=100.0,
            right_lanes=incoming_right if incoming_right is not None else _right(1),
        ),
        _line_road(
            "2",
            "5",
            x=connecting_x,
            y=connecting_y,
            hdg=connecting_hdg,
            length=connecting_length,
            right_lanes=connecting_right if connecting_right is not None else _right(1),
        ),
        _junction("5", "1", "2", contact_point, lane_links),
    )


# --- fixture 1: ~0.1m failing stub ------------------------------------------
def test_stub_01m_fitted():
    root = _incoming_and_connector(
        3.0, connecting_length=0.1, connecting_x=100.0, connecting_y=0.0
    )
    before_len = root.find("./road[@id='2']").get("length")
    report = fit_junction_connector_tangents(root)

    assert report["connectors_fitted"] == 1
    assert report["contact_point_start"] == 1
    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6, f"stub still severe-angle: {ang} deg"
    assert gap <= 1e-6
    # road length (laneSection s-range) preserved
    conn_road = root.find("./road[@id='2']")
    assert conn_road.get("length") == before_len == "0.1"
    # single paramPoly3 geometry
    geoms = _geoms(conn_road)
    assert len(geoms) == 1
    assert geoms[0].find("./paramPoly3") is not None
    assert geoms[0].find("./line") is None


# --- fixture 2: heading flip ------------------------------------------------
def test_heading_flip_fitted():
    root = _incoming_and_connector(math.pi, connecting_length=20.0)
    ang_before, _ = 180.0, None
    report = fit_junction_connector_tangents(root)

    assert report["connectors_fitted"] == 1
    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6, f"flipped connector not healed: {ang} deg"
    assert gap <= 1e-6
    assert ang < ang_before


# --- fixture 3: near-coincident endpoints -----------------------------------
def test_near_coincident_endpoints_fitted():
    root = _incoming_and_connector(
        0.4, connecting_x=100.001, connecting_y=0.0005, connecting_length=5.0
    )
    report = fit_junction_connector_tangents(root)

    assert report["connectors_fitted"] == 1
    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6
    assert gap <= 1e-6
    # contact snaps to the source-backed pose exactly
    conn = _connection(root)
    roads = _roads(root)
    contact = pose_at_s(_geoms(roads[str(conn.get("connectingRoad"))])[0], 0.0)
    src = endpoint(_geoms(roads[str(conn.get("incomingRoad"))])[-1])
    assert math.isclose(contact.x, src.x, abs_tol=1e-9)
    assert math.isclose(contact.y, src.y, abs_tol=1e-9)
    assert math.isclose(contact.heading, src.heading, abs_tol=1e-9)


# --- fixture 4: normal connector (moderate angle, far end preserved) --------
def test_normal_connector_fitted_far_end_preserved():
    hdg = 0.35
    length = 10.0
    root = _incoming_and_connector(hdg, connecting_length=length)
    roads_before = _roads(root)
    far_before = endpoint(_geoms(roads_before["2"])[-1])

    report = fit_junction_connector_tangents(root)
    assert report["connectors_fitted"] == 1

    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6
    assert gap <= 1e-6
    # Variant A contract: far endpoint pose (position + heading) preserved
    far_after = endpoint(_geoms(_roads(root)["2"])[-1])
    assert math.isclose(far_after.x, far_before.x, abs_tol=1e-6)
    assert math.isclose(far_after.y, far_before.y, abs_tol=1e-6)
    assert math.isclose(far_after.heading, far_before.heading, abs_tol=1e-6)
    # turning arc is the source heading vs the preserved far heading
    assert math.isclose(abs(hdg - 0.0), hdg, abs_tol=1e-9)


# --- fixture 5: lane-count reduction connector (laneLinks preserved) --------
def test_lane_count_reduction_connector_fitted_lanelinks_unchanged():
    lane_links = (
        '<laneLink from="-3" to="-1"/>'
        '<laneLink from="-2" to="-2"/>'
        '<laneLink from="-1" to="-1"/>'
    )
    root = _incoming_and_connector(
        0.30,
        incoming_right=_right(3),
        connecting_right=_right(2),
        lane_links=lane_links,
    )
    links_before = _lane_links_xml(root)

    report = fit_junction_connector_tangents(root)
    assert report["connectors_fitted"] == 1
    # laneLink topology byte-identical -> connection identity preserved
    assert _lane_links_xml(root) == links_before
    pairs = [
        (int(ll.get("from")), int(ll.get("to")))
        for ll in _connection(root).findall("laneLink")
    ]
    assert pairs == [(-3, -1), (-2, -2), (-1, -1)]
    # targets still resolve (no invalid targets introduced)
    connecting = _roads(root)["2"]
    section = connecting.find("./lanes/laneSection")
    to_ids = {
        int(l.get("id"))
        for l in section.find("./right").findall("lane")
        if l.get("type") == "driving"
    }
    assert {t for _, t in pairs} <= to_ids
    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6
    assert gap <= 1e-6


# --- fixture 6: contactPoint=start -----------------------------------------
def test_contact_point_start_fitted():
    root = _incoming_and_connector(0.5, connecting_length=12.0, contact_point="start")
    roads_before = _roads(root)
    geom_before = _geoms(roads_before["2"])[0]
    x_before, y_before = geom_before.get("x"), geom_before.get("y")

    report = fit_junction_connector_tangents(root)
    assert report["connectors_fitted"] == 1
    assert report["contact_point_start"] == 1

    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6
    assert gap <= 1e-6
    # contact already positionally aligned (the real-map case): position kept,
    # heading re-aimed to the incoming source heading.
    geom_after = _geoms(_roads(root)["2"])[0]
    assert math.isclose(float(geom_after.get("x")), float(x_before), abs_tol=1e-9)
    assert math.isclose(float(geom_after.get("y")), float(y_before), abs_tol=1e-9)
    src = endpoint(_geoms(_roads(root)["1"])[-1])
    assert math.isclose(float(geom_after.get("hdg")), src.heading, abs_tol=1e-9)


# --- fixture 7: contactPoint=end -------------------------------------------
def test_contact_point_end_fitted():
    # Connector END sits positionally on the incoming source pose (100, 0) --
    # the real-map situation -- but its line heading is 0.6 rad off. With
    # contactPoint=end the oracle flips by pi, giving a 145.6 deg angle.
    hdg = 0.6
    length = 40.0
    start_x = 100.0 - length * math.cos(hdg)
    start_y = 0.0 - length * math.sin(hdg)
    root = _incoming_and_connector(
        hdg, connecting_length=length, connecting_x=start_x, connecting_y=start_y,
        contact_point="end",
    )
    ang_before, gap_before = _angle_deg_and_gap(root)
    assert ang_before > _ANGLE_THRESHOLD_DEG, "fixture must start severe"
    assert gap_before <= 1e-9, "fixture contact must be positionally aligned"
    roads_before = _roads(root)
    far_geom_before = _geoms(roads_before["2"])[0]
    far_attrs_before = (
        far_geom_before.get("x"),
        far_geom_before.get("y"),
        far_geom_before.get("hdg"),
    )
    lanes_before = ET.tostring(
        roads_before["2"].find("./lanes"), encoding="unicode"
    )

    report = fit_junction_connector_tangents(root)
    assert report["connectors_fitted"] == 1
    assert report["contact_point_end"] == 1

    ang, gap = _angle_deg_and_gap(root)
    assert ang <= 1e-6, f"cp=end contact not healed: {ang} deg"
    assert gap <= 1e-6
    # far endpoint (the road's s=0 geometry pose) preserved to 1e-9
    far_geom_after = _geoms(_roads(root)["2"])[0]
    far_attrs_after = (
        far_geom_after.get("x"),
        far_geom_after.get("y"),
        far_geom_after.get("hdg"),
    )
    assert all(
        math.isclose(float(after), float(before), abs_tol=1e-9)
        for after, before in zip(far_attrs_after, far_attrs_before)
    )
    # lanes untouched
    assert ET.tostring(_roads(root)["2"].find("./lanes"), encoding="unicode") == lanes_before
    # road length preserved
    assert _roads(root)["2"].get("length") == roads_before["2"].get("length")


# --- fixture 8: previously passing control (must NOT be touched) ------------
def test_previously_passing_control_untouched():
    root = _incoming_and_connector(0.05, connecting_length=8.0)  # 2.86 deg < 12
    ang_before, _ = _angle_deg_and_gap(root)
    assert ang_before <= _ANGLE_THRESHOLD_DEG, "fixture must start passing"
    planview_before = ET.tostring(_roads(root)["2"].find("./planView"), encoding="unicode")
    links_before = _lane_links_xml(root)

    report = fit_junction_connector_tangents(root)

    assert report["connectors_fitted"] == 0
    assert report["skipped_within_threshold"] == 1
    assert report["contact_point_start"] == 0
    assert report["contact_point_end"] == 0
    assert ET.tostring(_roads(root)["2"].find("./planView"), encoding="unicode") == planview_before
    assert _lane_links_xml(root) == links_before
    ang_after, _ = _angle_deg_and_gap(root)
    assert math.isclose(ang_after, ang_before, abs_tol=1e-12)
