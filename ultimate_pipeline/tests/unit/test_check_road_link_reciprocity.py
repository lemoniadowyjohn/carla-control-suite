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


def test_junction_exit_side_is_backed_by_connecting_road_membership():
    # Connecting road A belongs to junction J1 (incoming I -> connecting A)
    # and leaves it into exit road B; B's predecessor names J1. No
    # <connection> names B (connections list only incoming/connecting
    # roads), so the pair is backed by A being one of J1's connecting
    # roads. On the real 07_lanes map every one-way exit has this shape.
    root = ET.Element("OpenDRIVE")
    root.append(_road("I", successor=("junction", "J1", None)))
    root.append(_road("A", junction="J1",
                      predecessor=("road", "I", "end"),
                      successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("junction", "J1", None)))
    root.append(_junction("J1", ("I", "A")))

    report = check_road_link_reciprocity(root)
    assert report["totals"]["junction_reference_unbacked_count"] == 0, report
    assert report["totals"]["junction_mediated_exempt"] == 2, report
    assert report["ok"] is True, report


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
