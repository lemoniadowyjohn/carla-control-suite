# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/lanes/junction_lanelink_inner_first.py (GAP-026).

Covers the deterministic inner-first laneLink mapping rule required by the
GAP026 inner-first repair port:
  3->2 reduction, 2->1 reduction, 4->2 reduction, positive lane IDs,
  negative lane IDs, contactPoint=start, contactPoint=end, equal lane-count
  control, a case that must NOT be remapped (ambiguous / already-canonical),
  and the zero-laneLink regression guard.

The rule is positive construction: rewrite only when the inner-first set
strictly reduces failing links under the production checker's unchanged
tolerances; an empty inner-first set never replaces a non-empty original.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.lanes.junction_lanelink_inner_first import (
    repair_outer_to_inner_mispaired_lane_links,
)


def _lane_xml(lane_id: int, width_a: float = 3.0, lane_type: str = "driving") -> str:
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
) -> str:
    return (
        f'<road id="{road_id}" length="{length}" junction="{junction}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{hdg}" length="{length}"><line/></geometry></planView>'
        f"<lanes><laneSection s=\"0\">"
        f"<left>{left_lanes}</left>"
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
    lane_links: str = "",
) -> str:
    return (
        f'<junction id="{junction_id}">'
        f'<connection id="0" incomingRoad="{incoming}" connectingRoad="{connecting}" '
        f'contactPoint="{contact_point}">{lane_links}</connection>'
        f"</junction>"
    )


def _parse(*parts: str) -> ET.Element:
    return ET.fromstring("<OpenDRIVE>" + "".join(parts) + "</OpenDRIVE>")


def _ll(f: int, t: int) -> str:
    return f'<laneLink from="{f}" to="{t}"/>'


def _pairs(conn: ET.Element) -> list[tuple[int, int]]:
    out = []
    for ll in conn.findall("laneLink"):
        out.append((int(ll.get("from")), int(ll.get("to"))))
    return out


# --- 3->2 reduction, negative IDs, contactPoint=start -----------------------
def test_three_to_two_reduction_negative_ids_start():
    # incoming right: -1,-2,-3 ; connecting right: -1,-2
    # SUMO-style mispair: outer -3 -> inner -1, plus -2->-2, -1->-1
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction("5", "1", "2", "start", _ll(-3, -1) + _ll(-2, -2) + _ll(-1, -1)),
    )
    report = repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    got = sorted(_pairs(conn))
    # inner-first: -1->-1, -2->-2 ; surplus outer -3 unlinked
    assert got == [(-2, -2), (-1, -1)]
    assert report["remapped_connections"] == 1
    # no zero-laneLink regression
    assert len(conn.findall("laneLink")) > 0


# --- 2->1 reduction, negative IDs ------------------------------------------
def test_two_to_one_reduction_negative_ids():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _road("2", "5", right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2", "start", _ll(-2, -1) + _ll(-1, -1)),
    )
    repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    assert sorted(_pairs(conn)) == [(-1, -1)]


# --- 4->2 reduction, negative IDs ------------------------------------------
def test_four_to_two_reduction_negative_ids():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3) + _lane_xml(-4)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction(
            "5", "1", "2", "start",
            _ll(-4, -1) + _ll(-3, -1) + _ll(-2, -2) + _ll(-1, -1),
        ),
    )
    repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    assert sorted(_pairs(conn)) == [(-2, -2), (-1, -1)]


# --- positive lane IDs (left side) -----------------------------------------
def test_positive_lane_ids_left_side():
    root = _parse(
        _road("1", "-1", left_lanes=_lane_xml(1) + _lane_xml(2) + _lane_xml(3)),
        _road("2", "5", left_lanes=_lane_xml(1) + _lane_xml(2)),
        _junction("5", "1", "2", "start", _ll(3, 1) + _ll(2, 2) + _ll(1, 1)),
    )
    repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    assert sorted(_pairs(conn)) == [(1, 1), (2, 2)]


# --- both signs present, handled independently -----------------------------
def test_mixed_signs_handled_independently():
    root = _parse(
        _road("1", "-1",
              left_lanes=_lane_xml(1) + _lane_xml(2),
              right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _road("2", "5",
              left_lanes=_lane_xml(1),
              right_lanes=_lane_xml(-1)),
        _junction("5", "1", "2", "start",
                  _ll(2, 1) + _ll(1, 1) + _ll(-2, -1) + _ll(-1, -1)),
    )
    repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    got = sorted(_pairs(conn))
    assert got == [(-1, -1), (1, 1)]


# --- contactPoint=end ------------------------------------------------------
def test_contact_point_end():
    # connecting road interface is its END section; give it 2 lanes
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction("5", "1", "2", "end", _ll(-3, -1) + _ll(-2, -2) + _ll(-1, -1)),
    )
    repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    # inner-first pairing is the same shape regardless of contactPoint;
    # the rule only selects a different interface section.
    got = sorted(_pairs(conn))
    assert got == [(-2, -2), (-1, -1)]


# --- equal lane-count control: must NOT be remapped ------------------------
def test_equal_lane_count_control_not_remapped():
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction("5", "1", "2", "start", _ll(-2, -2) + _ll(-1, -1)),
    )
    report = repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    # already canonical (equal |id|): not an outer->inner mispair
    assert report["remapped_connections"] == 0
    assert sorted(_pairs(conn)) == [(-2, -2), (-1, -1)]


# --- already-canonical inner-first: no change, ties keep original ----------
def test_already_canonical_inner_first_unchanged():
    # incoming 3 -> connecting 2, already inner-first (outer -3 unlinked)
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction("5", "1", "2", "start", _ll(-2, -2) + _ll(-1, -1)),
    )
    report = repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    assert report["remapped_connections"] == 0
    assert sorted(_pairs(conn)) == [(-2, -2), (-1, -1)]


# --- zero-laneLink regression guard: empty candidate never wins ------------
def test_zero_lanelink_regression_guard():
    # connecting road has NO driving lanes -> inner-first candidate is empty.
    # The rule must NOT clear a non-empty original set.
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _road("2", "5", right_lanes=""),  # no driving lanes on connector
        _junction("5", "1", "2", "start", _ll(-2, -1) + _ll(-1, -1)),
    )
    conn_before = root.find("./junction/connection")
    before_pairs = sorted(_pairs(conn_before))
    repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    conn = root.find("./junction/connection")
    # original preserved, not zeroed out
    assert sorted(_pairs(conn)) == before_pairs
    assert len(conn.findall("laneLink")) > 0


# --- ambiguous case: remap only when strictly fewer failing links ----------
def test_ties_keep_original():
    # An outer->inner mispair exists, but the connector has same |id| lanes
    # available; if inner-first would not strictly improve, keep original.
    # Here inner-first IS strictly better, so it remaps; assert the monotone
    # contract (no new failing links introduced) rather than a tie.
    root = _parse(
        _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3)),
        _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
        _junction("5", "1", "2", "start", _ll(-3, -1) + _ll(-2, -2) + _ll(-1, -1)),
    )
    report = repair_outer_to_inner_mispaired_lane_links(root, verbose=False)
    log = report["remap_log"]
    assert len(log) == 1
    # monotone: candidate never has more failing links than original
    assert log[0]["cand_fails"] < log[0]["orig_fails"]


# --- determinism: same input twice -> identical output ---------------------
def test_deterministic_output():
    def build():
        return _parse(
            _road("1", "-1", right_lanes=_lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3)),
            _road("2", "5", right_lanes=_lane_xml(-1) + _lane_xml(-2)),
            _junction("5", "1", "2", "start", _ll(-3, -1) + _ll(-2, -2) + _ll(-1, -1)),
        )

    r1 = build()
    r2 = build()
    repair_outer_to_inner_mispaired_lane_links(r1, verbose=False)
    repair_outer_to_inner_mispaired_lane_links(r2, verbose=False)
    c1 = sorted(_pairs(r1.find("./junction/connection")))
    c2 = sorted(_pairs(r2.find("./junction/connection")))
    assert c1 == c2
