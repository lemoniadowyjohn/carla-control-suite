# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/quality/check_road_link_reciprocity.py (L2).

New validation-only checker (no mutation):
(a) every road->road link has contactPoint in {start, end}.
(b) if road A's predecessor/successor is road B at B's start/end, B's
    reciprocal slot (predecessor if contact=="start", successor if
    contact=="end") must point back at A with the correctly-named
    contactPoint -- junction-mediated pairs are exempt.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_road_link_reciprocity import (
    check_road_link_reciprocity,
)


def _road(road_id, *, junction="-1", predecessor=None, successor=None):
    """predecessor/successor: (elementType, elementId, contactPoint_or_None)."""
    road = ET.Element("road", {"id": road_id, "junction": junction, "length": "10.0"})
    if predecessor is not None or successor is not None:
        link = ET.SubElement(road, "link")
        if predecessor is not None:
            et, eid, cp = predecessor
            attrs = {"elementType": et, "elementId": eid}
            if cp is not None:
                attrs["contactPoint"] = cp
            ET.SubElement(link, "predecessor", attrs)
        if successor is not None:
            et, eid, cp = successor
            attrs = {"elementType": et, "elementId": eid}
            if cp is not None:
                attrs["contactPoint"] = cp
            ET.SubElement(link, "successor", attrs)
    return road


def test_valid_reciprocal_pair_no_violations():
    # A's end -> B's start (A.successor contact=start); reciprocal:
    # B.predecessor -> A, contact=end (A's touched boundary is its end).
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("road", "A", "end")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report
    # Both directed <link> elements (A.successor and B.predecessor) are
    # each independently validated and both are reciprocally consistent.
    assert report["totals"]["road_road_links_checked"] == 2, report


def test_missing_contactpoint_is_a_violation():
    root = ET.Element("OpenDRIVE")
    road_a = _road("A", successor=("road", "B", None))  # no contactPoint
    root.append(road_a)
    root.append(_road("B", predecessor=("road", "A", "end")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is False, report
    assert report["totals"]["contactpoint_invalid_count"] == 1, report
    assert report["contactpoint_invalid_examples"][0]["road_id"] == "A"
    assert report["contactpoint_invalid_examples"][0]["slot"] == "successor"


def test_asymmetric_pair_is_a_violation():
    # A says successor=B@start, but B's predecessor points at someone else.
    # (The inconsistency is reciprocally visible from both A's and B's own
    # forward scan, so both directions legitimately surface a violation --
    # this asserts the one anchored at A, not an exact total count.)
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("road", "C", "end")))
    root.append(_road("C"))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is False, report
    assert report["totals"]["asymmetric_count"] >= 1, report
    found = [ex for ex in report["asymmetric_examples"] if ex["road_id"] == "A"]
    assert found, report
    assert found[0]["reciprocal_target_id"] == "C"
    assert found[0]["expected_reciprocal_contact_point"] == "end"


def test_asymmetric_wrong_contactpoint_is_a_violation():
    # B's predecessor correctly names A, but with the WRONG contactPoint
    # (should be "end" since A's touched boundary -- via its successor
    # slot -- is its own end).
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("road", "A", "start")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is False, report
    assert report["totals"]["asymmetric_count"] >= 1, report
    found = [ex for ex in report["asymmetric_examples"] if ex["road_id"] == "A"]
    assert found, report
    assert found[0]["reciprocal_contact_point"] == "start"
    assert found[0]["expected_reciprocal_contact_point"] == "end"


def _junction(junction_id, *connections):
    """connections: iterable of (incomingRoad, connectingRoad) pairs."""
    junction = ET.Element("junction", {"id": junction_id})
    for idx, (incoming, connecting) in enumerate(connections):
        ET.SubElement(
            junction,
            "connection",
            {
                "id": str(idx),
                "incomingRoad": incoming,
                "connectingRoad": connecting,
            },
        )
    return junction


def test_junction_mediated_pair_is_exempt():
    # A's successor points at B@start, but B's own predecessor (B's start
    # boundary) actually routes through a junction, not directly back to
    # A -- legitimate IFF junction J1 actually has a <connection> linking
    # A and B (ASAM: incoming roads point to the junction; connecting
    # roads' predecessor/successor name the incoming road).
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("junction", "J1", None)))
    root.append(_junction("J1", ("A", "B")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report
    assert report["totals"]["junction_mediated_exempt"] == 1, report
    assert report["totals"]["junction_reference_unbacked_count"] == 0, report


def test_junction_reference_without_backing_connection_is_a_violation():
    # Repro from the L2 review: junction J1 EXISTS but has no <connection>
    # that actually links A and B -- the old code exempted this pair just
    # because the reciprocal elementType wasn't "road". That is now a
    # distinct `junction_reference_unbacked` violation category.
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("junction", "J1", None)))
    # J1 exists, but its only connection is unrelated to the A/B pair.
    root.append(_junction("J1", ("Q", "R")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is False, report
    assert report["totals"]["junction_mediated_exempt"] == 0, report
    assert report["totals"]["junction_reference_unbacked_count"] == 1, report
    assert report["totals"]["violations"] >= 1, report
    found = [
        ex for ex in report["junction_reference_unbacked_examples"]
        if ex["road_id"] == "A"
    ]
    assert found, report
    assert found[0]["junction_id"] == "J1"
    assert found[0]["target_id"] == "B"


def _line(road, x, y, length=10.0, hdg=0.0):
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", {"s": "0", "x": str(x), "y": str(y),
                                     "hdg": str(hdg), "length": str(length)})
    ET.SubElement(plan.find("geometry"), "line")
    return road


def _exit_layout(*, a_junction="J1", b_x=20.0, b_hdg=0.0):
    # I (0..10) -> junction J1 via connecting road A (10..20) -> exit road B.
    root = ET.Element("OpenDRIVE")
    root.append(_line(_road("I", successor=("junction", "J1", None)), 0.0, 0.0))
    root.append(_line(_road("A", junction=a_junction,
                            predecessor=("road", "I", "end"),
                            successor=("road", "B", "start")), 10.0, 0.0))
    root.append(_line(_road("B", predecessor=("junction", "J1", None)), b_x, 0.0, hdg=b_hdg))
    root.append(_junction("J1", ("I", "A")))
    return root


def test_junction_exit_side_is_backed_by_connecting_road_membership():
    # Connecting road A belongs to junction J1 and leaves it into exit road B;
    # B's predecessor names J1. No <connection> names B (connections list
    # only incoming/connecting roads), so the exit is backed by A belonging to
    # J1 and A's end meeting B's start. On the real 07_lanes map every
    # one-way exit has this shape.
    report = check_road_link_reciprocity(_exit_layout())
    assert report["totals"]["junction_reference_unbacked_count"] == 0, report
    assert report["totals"]["junction_mediated_exempt"] == 2, report
    assert report["ok"] is True, report


def test_unrelated_road_claiming_a_junction_exit_is_reported_as_geometry_gap():
    # Review repro: A really is J1's connecting road, but the B it names sits
    # 500 m away. Structurally identical to a real exit; only the geometry
    # shows B is not where A leaves the junction. Geometry gaps are
    # report-only (the real map has 207 pre-existing ones, GAP-026 class),
    # so this must be listed, never silently exempt.
    report = check_road_link_reciprocity(_exit_layout(b_x=520.0))
    assert report["totals"]["junction_reference_unbacked_count"] == 0, report
    assert report["totals"]["junction_exit_geometry_gap_count"] == 1, report
    gap = report["junction_exit_geometry_gap_examples"][0]
    assert (gap["road_id"], gap["target_id"], gap["junction_id"]) == ("A", "B", "J1")
    assert gap["reference_line_gap_m"] == 500.0


def test_genuine_exit_has_no_geometry_gap():
    report = check_road_link_reciprocity(_exit_layout())
    assert report["totals"]["junction_exit_geometry_gap_count"] == 0, report


def test_exit_side_requires_connecting_road_to_belong_to_the_junction():
    # A is listed as J1's connectingRoad but its own junction attribute says
    # it is an ordinary road: inconsistent, so the exit is not backed.
    report = check_road_link_reciprocity(_exit_layout(a_junction="-1"))
    assert report["totals"]["junction_reference_unbacked_count"] == 1, report
    assert report["ok"] is False, report


def test_junction_reference_to_nonexistent_junction_is_a_violation():
    # The reciprocal link names a junction id that has no <junction>
    # element at all in the document -- clearly unbacked.
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("junction", "GHOST_J", None)))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is False, report
    assert report["totals"]["junction_mediated_exempt"] == 0, report
    assert report["totals"]["junction_reference_unbacked_count"] == 1, report


def test_junction_type_link_without_contactpoint_stays_fine():
    # A road-level successor/predecessor whose elementType is "junction"
    # legitimately has no contactPoint; this checker only applies the
    # contactPoint requirement to ROAD-type links.
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("junction", "J1", None)))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report
    assert report["totals"]["contactpoint_invalid_count"] == 0, report


def test_dangling_target_is_skipped_not_a_violation_here():
    # Target road doesn't exist -- that is check_lane_link_targets_exist's
    # concern, not this checker's; it must not be double-reported here.
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "GHOST", "start")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["dangling_target_skipped"] == 1, report
    assert report["totals"]["violations"] == 0, report


def test_predecessor_side_reciprocity():
    # A's start -> B's start (head-to-head): A.predecessor contact=start,
    # reciprocal B.predecessor -> A contact=start (A's touched boundary is
    # its own start, since the local slot is `predecessor`).
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", predecessor=("road", "B", "start")))
    root.append(_road("B", predecessor=("road", "A", "start")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report


# -- GAP-070: junction_exit_heading_discontinuity (report-only) -------------


def test_junction_exit_heading_discontinuity_zero_for_straight_continuation():
    # Base _exit_layout() is a dead-straight successor/start exit (A ends at
    # (20,0) hdg=0, B starts at (20,0) hdg=0): no tangent kink.
    report = check_road_link_reciprocity(_exit_layout())
    assert report["totals"]["junction_exit_heading_discontinuity_count"] == 0, report
    assert report["junction_exit_heading_discontinuity_examples"] == [], report
    # Report-only: must not affect ok/violations.
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report


def test_junction_exit_heading_discontinuity_detected_for_kinked_boundary():
    # Same successor/start exit, but B's reference line is rotated 53.13 deg
    # at the touching boundary -- the GAP-070 characterization's dominant
    # kink-exit shape (147/207 of the real map's junction_exit_geometry_gap
    # entries). Position still coincides (b_x=20.0 unchanged), so this is
    # NOT also a junction_exit_geometry_gap.
    report = check_road_link_reciprocity(_exit_layout(b_hdg=math.radians(53.13)))
    assert report["totals"]["junction_exit_geometry_gap_count"] == 0, report
    assert report["totals"]["junction_exit_heading_discontinuity_count"] == 1, report
    ex = report["junction_exit_heading_discontinuity_examples"][0]
    assert (ex["road_id"], ex["target_id"], ex["junction_id"]) == ("A", "B", "J1")
    assert abs(ex["heading_diff_deg"] - 53.13) < 0.01, report
    # Report-only: must not affect ok/violations.
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report


def test_junction_exit_heading_discontinuity_predecessor_contact_end_no_false_positive():
    # Direction-aware handling of the predecessor/contact="end" orientation
    # (both legs get the +pi reversal in _exit_heading_diff): B (hdg=37 deg)
    # flows straight into A's start, which is exactly where A's own
    # predecessor names B with contactPoint="end". This is a genuinely
    # continuous pair and must NOT be reported, exercising the reversed-slot
    # code path rather than just the trivial successor/start case above.
    hdg = math.radians(37.0)
    root = ET.Element("OpenDRIVE")
    root.append(_line(_road("B", successor=("junction", "J1", None)), 0.0, 0.0, hdg=hdg))
    bend_x = 10.0 * math.cos(hdg)
    bend_y = 10.0 * math.sin(hdg)
    root.append(_line(
        _road("A", junction="J1", predecessor=("road", "B", "end")),
        bend_x, bend_y, hdg=hdg,
    ))
    root.append(_junction("J1", ("I", "A")))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report
    assert report["totals"]["junction_mediated_exempt"] == 1, report
    assert report["totals"]["junction_exit_geometry_gap_count"] == 0, report
    assert report["totals"]["junction_exit_heading_discontinuity_count"] == 0, report
