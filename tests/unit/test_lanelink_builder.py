"""LaneLinkBuilder regression fixtures (Lane T).

Failure-mode taxonomy of the inner-first junction pairing: no fallback
pairing is permitted (GAP-048 policy), so unlinked driving lanes must be
classified, not silently dropped, and degenerate zero-length terminal
sections must not mask the real interface pairing.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT),):
    if p not in sys.path:
        sys.path.insert(0, p)

from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder  # noqa: E402


def _road(rid, lanes_right, junction="-1", length="20.0", sections=None):
    """lanes_right: list of (id, width) pairs; width None => no width element."""
    lane_parts = []
    for lid, w in lanes_right:
        if w is not None:
            lane_parts.append(
                '<lane id="%s" type="driving">'
                '<width sOffset="0" a="%s" b="0" c="0" d="0"/></lane>' % (lid, w)
            )
        else:
            lane_parts.append('<lane id="%s" type="driving"/>' % lid)
    lane_xml = "".join(lane_parts)
    link = (
        '<link><successor elementType="junction" elementId="10"/></link>'
        if junction == "-1"
        else '<link><predecessor elementType="junction" elementId="10"/></link>'
    )
    return (
        '<road id="%s" name="r%s" junction="%s" length="%s">'
        "%s"
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="%s"><line/></geometry></planView>'
        '<lanes>%s<laneSection s="0"><left/><right>%s</right></laneSection></lanes>'
        "</road>"
        % (rid, rid, junction, length, link, length, sections or "", lane_xml)
    )


def _root(incoming_xml, connector_xml="", extra_junction=""):
    return ET.fromstring(
        "<OpenDRIVE>"
        '<header revMajor="1" revMinor="4" length="20"/>'
        + incoming_xml
        + connector_xml
        + '<junction id="10">'
        '<connection id="0" incomingRoad="1" connectingRoad="9" contactPoint="start">'
        "</connection>"
        + extra_junction
        + "</junction>"
        + "</OpenDRIVE>"
    )


def _report():
    return LaneLinkBuilder.last_failure_report


def test_inner_first_pairing_for_equal_lane_counts():
    incoming = _road("1", [(-1, 3.0), (-2, 3.0)])
    connector = _road("9", [(-1, 3.0), (-2, 3.0)], junction="10")
    root = _root(incoming, connector)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    links = {
        (ll.get("from"), ll.get("to"))
        for ll in root.findall("junction/connection/laneLink")
    }
    assert links == {("-1", "-1"), ("-2", "-2")}
    assert _report()["summary"] == {} or all(d == 0 for d in _report()["summary"].values())


def test_count_mismatch_leaves_no_fallback_pairing_but_is_classified():
    incoming = _road("1", [(-1, 3.0), (-2, 3.0)])      # 2 right driving lanes
    connector = _road("9", [(-1, 3.0)])                # connector has only 1
    root = _root(incoming, connector)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)

    links = {
        (ll.get("from"), ll.get("to"))
        for ll in root.findall("junction/connection/laneLink")
    }
    assert links == {("-1", "-1")}, "inner-first pairing only; no cross-order guess"
    rep = _report()
    assert rep["summary"].get("COUNT_MISMATCH_INNER_FIRST_EXHAUSTED") == 1
    rec = rep["records"][0]
    assert rec["lane_id"] == -2
    assert rec["incoming"] == "1"
    assert rec["connector_lanes"] == [-1]


def test_widthless_incoming_lane_is_skipped_and_classified():
    incoming = _road("1", [(-1, 3.0), (-2, None)])     # outer lane without width
    connector = _road("9", [(-1, 3.0), (-2, 3.0)])
    root = _root(incoming, connector)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)

    links = {
        (ll.get("from"), ll.get("to"))
        for ll in root.findall("junction/connection/laneLink")
    }
    assert links == {("-1", "-1")}
    assert _report()["summary"].get("INCOMING_LANE_NO_WIDTH") == 1


def test_connector_with_no_driving_lane_on_side_is_classified():
    incoming = _road("1", [(-1, 3.0)])
    geom = (
        '<road id="9" name="c9" junction="10" length="20">'
        '<link><predecessor elementType="junction" elementId="10"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><left/><right><lane id="0" type="none"/></right></laneSection></lanes>'
        "</road>"
    )
    root = _root(incoming, geom)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    assert root.findall("junction/connection/laneLink") == []
    assert _report()["summary"].get("CONNECTOR_SIDE_NO_DRIVING_LANES") == 1


def test_degenerate_zero_length_terminal_section_is_filtered():
    # Incoming road's LAST section sits exactly at s == length (zero length):
    # the real interface is the previous section.
    real_section = '<laneSection s="0"><left/><right>' + (
        '<lane id="-1" type="driving"><width sOffset="0" a="3" b="0" c="0" d="0"/></lane>'
    ) + "</right></laneSection>"
    degenerate = '<laneSection s="20"><left/><right>' + (
        '<lane id="-1" type="driving"/>'
    ) + "</right></laneSection>"
    incoming_x = (
        '<road id="1" name="r1" junction="-1" length="20">'
        '<link><successor elementType="junction" elementId="10"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20"><line/></geometry></planView>'
        f"<lanes>{real_section}{degenerate}</lanes></road>"
    )
    connector = _road("9", [(-1, 3.0)], junction="10")
    root = _root(incoming_x, connector)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)

    links = [
        (ll.get("from"), ll.get("to"))
        for ll in root.findall("junction/connection/laneLink")
    ]
    assert links == [("-1", "-1")], "real terminal face must drive the pairing"
    # the degenerate widthless section must not surface as a failure either
    assert _report()["summary"].get("INCOMING_LANE_NO_WIDTH") in (None, 0)


def test_failure_report_is_bounded_and_shape_stable():
    incoming = _road("1", [(-1, 3.0), (-2, 3.0), (-3, 3.0), (-4, 3.0)])
    connector = _road("9", [(-1, 3.0)])
    root = _root(incoming, connector)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    rep = _report()
    assert set(("summary", "records", "connections_total", "lane_links_emitted")) <= set(rep)
    assert rep["connections_total"] == 1
    assert rep["lane_links_emitted"] == 1
    for rec in rep["records"]:
        assert "reason" in rec and "junction_id" in rec


def test_missing_connector_interface_is_classified():
    incoming = _road("1", [(-1, 3.0)])
    connector_no_lanes = (
        '<road id="9" name="c9" junction="10" length="20">'
        '<link><predecessor elementType="junction" elementId="10"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20"><line/></geometry></planView>'
        "<lanes></lanes></road>"
    )
    root = _root(incoming, connector_no_lanes)
    LaneLinkBuilder.regenerate_lane_links(root, verbose=False)
    assert _report()["summary"].get("CONNECTOR_MISSING_INTERFACE_SECTION") == 1
    assert root.findall("junction/connection/laneLink") == []
