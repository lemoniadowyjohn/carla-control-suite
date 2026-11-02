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


def test_junction_mediated_pair_is_exempt():
    # A's successor points at B@start, but B's own predecessor (B's start
    # boundary) actually routes through a junction, not directly back to
    # A -- this is a legitimate junction-mediated connection.
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", successor=("road", "B", "start")))
    root.append(_road("B", predecessor=("junction", "J1", None)))

    report = check_road_link_reciprocity(root)
    assert report["ok"] is True, report
    assert report["totals"]["violations"] == 0, report
    assert report["totals"]["junction_mediated_exempt"] == 1, report


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
