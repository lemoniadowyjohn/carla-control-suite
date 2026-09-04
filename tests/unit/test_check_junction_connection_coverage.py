"""check_junction_connection_coverage.py -- round-4 scoping plan, WS-1.

Detects roads whose junction-typed <link> isn't cited as `incomingRoad` in
that junction's own <connection> list (round-3 WS-H found this pattern on
~29% of roads in the real map-of-record candidate, see
reports/post_audit_hardening/WS_H_ISOLATED_LANE_JUNCTION_CONNECTION_20260904.md).
This module only classifies each gap (CONFIDENT/AMBIGUOUS/NO_CANDIDATE) --
it never mutates the XODR tree.
"""
import math
import xml.etree.ElementTree as ET

import ultimate_pipeline.quality.check_junction_connection_coverage as mod
from ultimate_pipeline.quality.check_junction_connection_coverage import (
    AMBIGUOUS,
    CONFIDENT,
    NO_CANDIDATE,
    check_junction_connection_coverage,
)


def _road(rid, x, y, hdg, length, junction="-1", link=None):
    r = ET.Element("road", id=rid, junction=junction, length=str(length))
    pv = ET.SubElement(r, "planView")
    geom = ET.SubElement(pv, "geometry", s="0", x=str(x), y=str(y), hdg=str(hdg), length=str(length))
    ET.SubElement(geom, "line")
    if link:
        link_el = ET.SubElement(r, "link")
        kind, etype, eid = link
        ET.SubElement(link_el, kind, elementType=etype, elementId=eid)
    return r


def _junction(jid, connections):
    j = ET.Element("junction", id=jid)
    for i, (incoming, connecting, contact_point) in enumerate(connections):
        ET.SubElement(
            j, "connection", id=str(i), incomingRoad=incoming, connectingRoad=connecting,
            contactPoint=contact_point,
        )
    return j


def test_confident_single_geometric_match():
    root = ET.Element("OpenDRIVE")
    # Road "1" approaches junction "10" at its own start (predecessor).
    road1 = _road("1", x=0, y=0, hdg=0, length=10, link=("predecessor", "junction", "10"))
    # Connecting road "2" starts at (0,0) with hdg=pi -- expected delta for
    # start<->start is pi (opposite tangents at a shared point), so this is
    # an exact geometric match for road 1's approach.
    road2 = _road("2", x=0, y=0, hdg=math.pi, length=5, junction="10")
    # Junction 10 already has a connection from some OTHER road ("3") using
    # connecting road "2" -- road "1" itself is NOT cited, that's the gap.
    road3 = _road("3", x=100, y=100, hdg=0, length=5, link=("successor", "junction", "10"))
    junction10 = _junction("10", [("3", "2", "start")])

    for el in (road1, road2, road3, junction10):
        root.append(el)

    rep = check_junction_connection_coverage(root)

    gaps_for_road1 = [g for g in rep["gaps"] if g["road_id"] == "1"]
    assert len(gaps_for_road1) == 1
    gap = gaps_for_road1[0]
    assert gap["classification"] == CONFIDENT
    assert gap["match"]["connecting_road"] == "2"
    assert gap["match"]["contact_point"] == "start"
    assert gap["match"]["dxy_m"] < 1e-6
    assert rep["confident_count"] == 1
    assert rep["ambiguous_count"] == 0
    assert rep["no_candidate_count"] == 0


def test_ambiguous_when_two_candidates_coincide():
    root = ET.Element("OpenDRIVE")
    road1 = _road("1", x=0, y=0, hdg=0, length=10, link=("predecessor", "junction", "10"))
    # Two connecting roads BOTH start at (0,0) with hdg=pi -- a real pattern
    # this session found on the actual map-of-record candidate (multiple
    # connector roads physically coincide at a junction's shared attachment
    # point) -- must not guess between them.
    road2 = _road("2", x=0, y=0, hdg=math.pi, length=5, junction="10")
    road4 = _road("4", x=0, y=0, hdg=math.pi, length=5, junction="10")
    road3 = _road("3", x=100, y=100, hdg=0, length=5, link=("successor", "junction", "10"))
    junction10 = _junction("10", [("3", "2", "start"), ("3", "4", "start")])

    for el in (road1, road2, road4, road3, junction10):
        root.append(el)

    rep = check_junction_connection_coverage(root)

    gaps_for_road1 = [g for g in rep["gaps"] if g["road_id"] == "1"]
    assert len(gaps_for_road1) == 1
    gap = gaps_for_road1[0]
    assert gap["classification"] == AMBIGUOUS
    assert len(gap["candidates"]) == 2
    assert rep["confident_count"] == 0
    assert rep["ambiguous_count"] == 1


def test_no_candidate_when_nothing_within_tolerance():
    root = ET.Element("OpenDRIVE")
    road1 = _road("1", x=0, y=0, hdg=0, length=10, link=("predecessor", "junction", "10"))
    # Connecting road is far away (1000m) -- well outside tolerance_m=5.0.
    road2 = _road("2", x=1000, y=1000, hdg=math.pi, length=5, junction="10")
    road3 = _road("3", x=100, y=100, hdg=0, length=5, link=("successor", "junction", "10"))
    junction10 = _junction("10", [("3", "2", "start")])

    for el in (road1, road2, road3, junction10):
        root.append(el)

    rep = check_junction_connection_coverage(root)

    gaps_for_road1 = [g for g in rep["gaps"] if g["road_id"] == "1"]
    assert len(gaps_for_road1) == 1
    assert gaps_for_road1[0]["classification"] == NO_CANDIDATE
    assert rep["no_candidate_count"] == 1


def test_no_gap_when_road_already_cited():
    root = ET.Element("OpenDRIVE")
    road1 = _road("1", x=0, y=0, hdg=0, length=10, link=("predecessor", "junction", "10"))
    road2 = _road("2", x=0, y=0, hdg=math.pi, length=5, junction="10")
    junction10 = _junction("10", [("1", "2", "start")])  # road 1 correctly cited

    for el in (road1, road2, junction10):
        root.append(el)

    rep = check_junction_connection_coverage(root)

    assert rep["total_gaps"] == 0
    assert rep["gaps"] == []


def test_roundabout_junctions_are_skipped(monkeypatch):
    root = ET.Element("OpenDRIVE")
    road1 = _road("1", x=0, y=0, hdg=0, length=10, link=("predecessor", "junction", "10"))
    road2 = _road("2", x=0, y=0, hdg=math.pi, length=5, junction="10")
    road3 = _road("3", x=100, y=100, hdg=0, length=5, link=("successor", "junction", "10"))
    junction10 = _junction("10", [("3", "2", "start")])

    for el in (road1, road2, road3, junction10):
        root.append(el)

    # Same shape as test_confident_single_geometric_match, but junction "10"
    # is (per this monkeypatch) classified as a roundabout -- its connection
    # list is wholesale-rewritten elsewhere in the pipeline, so a gap here
    # may be a stale/mid-transformation artifact, not a genuine converter bug.
    monkeypatch.setattr(
        mod._RoundaboutDetector, "detect",
        staticmethod(lambda root: ({"10": {"roads": ["2"], "center": (0.0, 0.0)}}, {})),
    )

    rep = check_junction_connection_coverage(root)

    assert rep["total_gaps"] == 0
    # Both road "1" (the gap) and road "3" (already correctly cited, but
    # still carries its own junction-typed link) have a junction link to the
    # now-roundabout-classified junction 10, so both get skipped and counted.
    assert rep["skipped_roundabout_junction_links"] == 2


def test_returns_no_xml_mutation():
    root = ET.Element("OpenDRIVE")
    road1 = _road("1", x=0, y=0, hdg=0, length=10, link=("predecessor", "junction", "10"))
    road2 = _road("2", x=0, y=0, hdg=math.pi, length=5, junction="10")
    road3 = _road("3", x=100, y=100, hdg=0, length=5, link=("successor", "junction", "10"))
    junction10 = _junction("10", [("3", "2", "start")])

    for el in (road1, road2, road3, junction10):
        root.append(el)

    before = ET.tostring(root)
    check_junction_connection_coverage(root)
    after = ET.tostring(root)

    assert before == after
