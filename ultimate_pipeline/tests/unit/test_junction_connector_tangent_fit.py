# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/topology/junction_connector_tangent_fit.py.

GAP-026 severe-angle closure: narrow per-connector normalized-paramPoly3
Hermite repair. Covers exactly:
  1. ~0.1 m failing stub
  2. heading-flip connector
  3. near-coincident endpoints
  4. normal connector
  5. lane-count-reduction connector
  6. contactPoint=start
  7. contactPoint=end
  8. previously passing control
plus: invalid anchors unchanged, finite coefficients, topology identity,
idempotence, and determinism.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.topology.junction_connector_tangent_fit import (
    apply_junction_connector_tangent_fit,
)


def _lane_xml(lane_id: int, width_a: float = 3.5, lane_type: str = "driving") -> str:
    return (
        f'<lane id="{lane_id}" type="{lane_type}">'
        f'<width sOffset="0" a="{width_a}" b="0" c="0" d="0"/>'
        f"</lane>"
    )


def _road(
    road_id: str,
    junction: str,
    right_lanes: str = "",
    left_lanes: str = "",
    *,
    x: float = 0.0,
    y: float = 0.0,
    hdg: float = 0.0,
    length: float = 10.0,
    successor: str = "",
) -> str:
    return (
        f'<road id="{road_id}" length="{length}" junction="{junction}">'
        f"{successor}"
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{hdg}" length="{length}"><line/></geometry></planView>'
        f"<lanes><laneSection s=\"0\">"
        f"<left>{left_lanes}</left>"
        f'<center><lane id="0" type="none"/></center>'
        f"<right>{right_lanes}</right>"
        f"</laneSection></lanes>"
        f"</road>"
    )


def _junction(junction_id: str, incoming: str, connecting: str, contact_point: str = "start") -> str:
    return (
        f'<junction id="{junction_id}">'
        f'<connection id="0" incomingRoad="{incoming}" connectingRoad="{connecting}" contactPoint="{contact_point}">'
        f'<laneLink from="-1" to="-1"/>'
        f"</connection>"
        f"</junction>"
    )


def _rsucc(element_id: str) -> str:
    return (
        f'<link><successor elementType="junction" elementId="{element_id}" contactPoint="start"/></link>'
    )


def _rpre(element_id: str) -> str:
    return (
        f'<link><predecessor elementType="road" elementId="{element_id}" contactPoint="start"/></link>'
        + f'<link><successor elementType="road" elementId="{element_id}" contactPoint="end"/></link>'
    )


def _tree(incoming_succ: str, conn_geom: str, outgoing: str = "", junction: str = "") -> ET.Element:
    return ET.fromstring(f"<OpenDRIVE>{incoming_succ}{conn_geom}{outgoing}{junction}</OpenDRIVE>")


def _geom_of(root: ET.Element, road_id: str) -> ET.Element:
    road = next(r for r in root.findall("road") if r.get("id") == road_id)
    geoms = road.findall("./planView/geometry")
    assert len(geoms) == 1
    return geoms[0]


def _conn_prim(root: ET.Element, road_id: str) -> str:
    geom = _geom_of(root, road_id)
    kids = list(geom)
    assert len(kids) == 1
    return kids[0].tag


# 1. ~0.1 m failing stub ----------------------------------------------------
def test_failing_stub_rebuilt():
    # 0.1 m connector whose start heading is 0.5 rad off the incoming tangent.
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.5, length=0.1,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=10.1, y=0, hdg=0, length=10),
        _junction("J1", "R1", "C1"),
    )
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 1
    assert _conn_prim(root, "C1") == "paramPoly3"


# 2. heading-flip connector ---------------------------------------------------
def test_heading_flip_rebuilt():
    # Connector start heading ~180 deg off: angular error dominates.
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=math.pi - 0.1, length=5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=16, y=0, hdg=0, length=10),
        _junction("J1", "R1", "C1"),
    )
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 1
    assert _conn_prim(root, "C1") == "paramPoly3"


# 3. near-coincident endpoints ------------------------------------------------
def test_near_coincident_endpoints_rebuilt():
    # Start and end nearly coincide (tight U-turn stub, chord ~0.05 m).
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=1.2, length=0.5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=10.04, y=0.01, hdg=2.4, length=10),
        _junction("J1", "R1", "C1"),
    )
    rep = apply_junction_connector_tangent_fit(root)
    # Either rebuilt or explicitly rejected (degenerate chord) -- never crash.
    assert rep["rebuilt"] + rep["rejected"] == 1
    if rep["rebuilt"] == 1:
        assert _conn_prim(root, "C1") == "paramPoly3"


# 4. normal connector ----------------------------------------------------------
def test_normal_connector_rebuilt():
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.4, length=6,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=16, y=1, hdg=0.1, length=10),
        _junction("J1", "R1", "C1"),
    )
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 1
    geom = _geom_of(root, "C1")
    assert geom.find("paramPoly3").get("pRange") == "normalized"


# 5. lane-count-reduction connector --------------------------------------------
def test_lane_count_reduction_connector():
    # Incoming has 2 lanes, connector has 1: geometry repair must not touch
    # lane topology (laneLinks/connections unchanged, s-bounds hold).
    root = _tree(
        _road("R1", "-1",
              right_lanes=_lane_xml(-1) + _lane_xml(-2), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.6, length=5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=15, y=1, hdg=0, length=10),
        _junction("J1", "R1", "C1"),
    )
    n_ll_before = len(root.findall(".//laneLink"))
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 1
    assert len(root.findall(".//laneLink")) == n_ll_before
    # laneSection s still within road bounds
    road = next(r for r in root.findall("road") if r.get("id") == "C1")
    length = float(road.get("length"))
    for sec in road.findall("./lanes/laneSection"):
        assert 0.0 <= float(sec.get("s")) <= length + 1e-6


# 6. contactPoint=start ---------------------------------------------------------
def test_contact_point_start():
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=-0.5, length=5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=15, y=-1, hdg=0, length=10),
        _junction("J1", "R1", "C1", contact_point="start"),
    )
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 1
    assert _conn_prim(root, "C1") == "paramPoly3"


# 7. contactPoint=end ------------------------------------------------------------
def test_contact_point_end():
    # Connector attaches to the junction at its END geometry.
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
                successor=_rsucc("J1"))
        +         '<road id="C1" length="5" junction="J1">'
          '<link><predecessor elementType="road" elementId="R0" contactPoint="end"/></link>'
          '<planView><geometry s="0" x="5" y="0" hdg="0.6" length="5"><line/></geometry></planView>'
          '<lanes><laneSection s="0"><left></left>'
          '<center><lane id="0" type="none"/></center>'
          f"<right>{_lane_xml(-1)}</right>"
          "</laneSection></lanes>"
          "</road>"
        + _road("R0", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0.5, length=5)
        + '<junction id="J1">'
          '<connection id="0" incomingRoad="R1" connectingRoad="C1" contactPoint="end">'
          '<laneLink from="-1" to="-1"/>'
          "</connection>"
          "</junction>"
        + "</OpenDRIVE>"
    )
    rep = apply_junction_connector_tangent_fit(root)
    # Either rebuilt or explicitly rejected with reason (end-attach path).
    assert rep["rebuilt"] + rep["rejected"] + rep["skipped_no_anchor"] == 1
    assert rep["connectors_examined"] == 1


# 8. previously passing control --------------------------------------------------
def test_already_valid_connector_untouched():
    # Start heading aligned (0.01 rad): must be skipped, geometry identical.
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.01, length=5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=15, y=0, hdg=0, length=10),
        _junction("J1", "R1", "C1"),
    )
    before = ET.tostring(root.find(".//road[@id='C1']/planView"))
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 0
    assert rep["skipped_valid"] == 1
    assert ET.tostring(root.find(".//road[@id='C1']/planView")) == before


# --- additional required behaviors ----------------------------------------------
def test_invalid_anchors_unchanged():
    # Incoming road missing: connector left unchanged, rejection recorded.
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.8, length=5)
        + '<junction id="J1">'
          '<connection id="0" incomingRoad="RX" connectingRoad="C1" contactPoint="start">'
          '<laneLink from="-1" to="-1"/>'
          "</connection>"
          "</junction>"
        + "</OpenDRIVE>"
    )
    before = ET.tostring(root.find(".//road[@id='C1']/planView"))
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 0
    assert rep["skipped_no_anchor"] == 1
    assert ET.tostring(root.find(".//road[@id='C1']/planView")) == before


def test_coefficients_finite():
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.9, length=4,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=14, y=1, hdg=0.2, length=10),
        _junction("J1", "R1", "C1"),
    )
    rep = apply_junction_connector_tangent_fit(root)
    assert rep["rebuilt"] == 1
    pp = _geom_of(root, "C1").find("paramPoly3")
    import math
    for k in ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV"):
        assert math.isfinite(float(pp.get(k)))


def test_topology_identity_unchanged():
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.7, length=5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=15, y=1, hdg=0, length=10),
        _junction("J1", "R1", "C1"),
    )
    def ident(r):
        return (
            sum(len(j.findall("connection")) for j in r.findall("junction")),
            sum(len(c.findall("laneLink")) for j in r.findall("junction") for c in j.findall("connection")),
            sum(len((rr.find("link") or [])) for rr in r.findall("road")),
        )
    before = ident(root)
    apply_junction_connector_tangent_fit(root)
    assert ident(root) == before


def test_repeated_application_idempotent():
    root = _tree(
        _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
              successor=_rsucc("J1")),
        _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.6, length=5,
              successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
        _road("R2", "-1", right_lanes=_lane_xml(-1), x=15, y=1, hdg=0, length=10),
        _junction("J1", "R1", "C1"),
    )
    first = apply_junction_connector_tangent_fit(root)
    assert first["rebuilt"] == 1
    snap = ET.tostring(root.find(".//road[@id='C1']/planView"))
    second = apply_junction_connector_tangent_fit(root)
    assert second["rebuilt"] == 0
    assert second["skipped_valid"] == 1
    assert ET.tostring(root.find(".//road[@id='C1']/planView")) == snap


def test_deterministic_output():
    def build():
        return _tree(
            _road("R1", "-1", right_lanes=_lane_xml(-1), x=0, y=0, hdg=0, length=10,
                  successor=_rsucc("J1")),
            _road("C1", "J1", right_lanes=_lane_xml(-1), x=10, y=0, hdg=0.55, length=5,
                  successor='<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'),
            _road("R2", "-1", right_lanes=_lane_xml(-1), x=15, y=1, hdg=0, length=10),
            _junction("J1", "R1", "C1"),
        )
    r1, r2 = build(), build()
    apply_junction_connector_tangent_fit(r1)
    apply_junction_connector_tangent_fit(r2)
    assert ET.tostring(r1) == ET.tostring(r2)
