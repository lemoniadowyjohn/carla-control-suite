# tests/unit/test_geometric_continuity_contactpoint.py
# -*- coding: utf-8 -*-

"""
Characterization tests for CODEX C6 (geometric-continuity checker correctness).

See reports/post_audit_hardening/C6_CONTINUITY_CHECKER.md and
reports/post_audit_hardening/C6_geometric_continuity_checker_correctness.md
(the original problem spec) for full context.

Root cause (pre-fix): `check_geometric_continuity` always compared road A's
END pose to road B's START pose, ignoring `link_kind` (predecessor vs
successor) and `contactPoint`. That produced ~27193 false-positive
"discontinuities" on the C0 candidate, dominated by:
  - predecessor links compared at the wrong end of A, and
  - end-contact ("anti-parallel by design") links flagged for a ~pi heading
    delta that is actually correct for that topology.

This module has two kinds of tests:

1. `TestNaiveCheckerIsWrong` -- a local, deliberately-naive reimplementation
   of the ORIGINAL buggy comparison (A.end -> B.start, ignoring link_kind and
   contactPoint) is exercised directly against the fixtures to prove those
   fixtures really would have been flagged by the old logic (RED evidence).
   This is not testing production code; it pins down the bug this task fixes
   so the characterization is falsifiable.

2. `TestCorrectedChecker*` -- exercises the CURRENT
   `ultimate_pipeline.quality.check_geometric_continuity.check_geometric_continuity`
   and asserts it passes the same fixtures, plus a negative control (a
   genuine 5 m gap) that must still fail under both the naive and the
   corrected checker.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Optional

import pytest

from ultimate_pipeline.quality.check_geometric_continuity import (
    _angle_diff,
    _parse_geometries,
    _pose_at_s,
    _road_length,
    check_geometric_continuity,
)


def _write_xodr(tmp_path, body: str) -> str:
    path = tmp_path / "links.xodr"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<header revMajor="1" revMinor="6"/>'
        f"{body}"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    return str(path)


# ----------------------------------------------------------------------
# Fixture 1: predecessor + contactPoint="end".
# Road 2's predecessor is road 1, contact at road 1's END (not start).
# Road 2's "start" endpoint (predecessor is anchored at the source road's
# start) meets road 1's "end" endpoint: a start<->end join, which is
# co-directional (same heading) along the reference line -- unlike a
# start<->start or end<->end join, which is anti-parallel by design (see
# Fixture 1b below, and `_expected_heading_delta_rad`).
# ----------------------------------------------------------------------
def _predecessor_end_contact_body() -> str:
    return (
        '<road id="1" length="10" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="5" junction="-1">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="5"><line/></geometry></planView>'
        "</road>"
    )


# ----------------------------------------------------------------------
# Fixture 1b: successor + contactPoint="end". Both endpoints are "end"-type
# (from_endpoint="end" for a successor link, to_endpoint="end" for
# contactPoint="end"), which IS the anti-parallel-by-design case: the two
# roads' reference-line tangents point in opposite directions at the shared
# point. This is the fixture the naive checker gets wrong via a ~pi heading
# "false discontinuity" (see C6 spec evidence table).
# ----------------------------------------------------------------------
def _successor_end_contact_anti_parallel_body() -> str:
    return (
        '<road id="1" length="10" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="5" junction="-1">'
        f'<planView><geometry s="0" x="15" y="0" hdg="{math.pi}" length="5"><line/></geometry></planView>'
        "</road>"
    )


# ----------------------------------------------------------------------
# Fixture 2: successor + contactPoint="start". Co-linear, same heading.
# ----------------------------------------------------------------------
def _successor_start_contact_body() -> str:
    return (
        '<road id="1" length="10" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="5" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="5"><line/></geometry></planView>'
        "</road>"
    )


# ----------------------------------------------------------------------
# Fixture 3: negative control. Endpoints 5 m apart (genuine gap). Must
# fail under BOTH the naive and the corrected checker -- honoring
# contactPoint must never mask a real discontinuity.
# ----------------------------------------------------------------------
def _negative_control_5m_gap_body() -> str:
    return (
        '<road id="1" length="10" junction="-1">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="5" junction="-1">'
        # Road 1 ends at x=10; road 2 "start" is placed 5 m further away at x=15.
        '<planView><geometry s="0" x="15" y="0" hdg="0" length="5"><line/></geometry></planView>'
        "</road>"
    )


def _naive_link_check(xodr_path: str, eps_xy: float = 0.05, eps_hdg: float = 0.01):
    """
    Deliberately-naive reimplementation of the PRE-FIX comparison: always
    compares road A's END pose to road B's START pose, ignoring link_kind
    and contactPoint entirely. Used only to characterize/pin the bug this
    task fixes -- never call this in production code.

    Returns a list of (from_road, to_road, link_kind, dxy, dhdg) tuples for
    every road-to-road link whose naive comparison exceeds eps_xy/eps_hdg.
    """
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    road_by_id = {}
    for r in root.findall("road"):
        rid = (r.get("id") or "").strip()
        if rid:
            road_by_id[rid] = r

    geom_cache = {}

    def get_geoms(rid: str):
        if rid not in geom_cache:
            r = road_by_id.get(rid)
            geom_cache[rid] = _parse_geometries(r) if r is not None else ([], [])
        return geom_cache[rid]

    bad = []
    for r in root.findall("road"):
        rid = (r.get("id") or "").strip()
        link_el = r.find("link")
        if link_el is None:
            continue
        for kind in ("predecessor", "successor"):
            el = link_el.find(kind)
            if el is None:
                continue
            etype = (el.get("elementType") or "").strip()
            eid = (el.get("elementId") or "").strip()
            if etype != "road" or eid not in road_by_id:
                continue
            geoms_a, _ = get_geoms(rid)
            geoms_b, _ = get_geoms(eid)
            len_a = _road_length(r)
            # NAIVE: always A.end -> B.start, ignoring link_kind/contactPoint.
            pose_end_a, _ = _pose_at_s(geoms_a, len_a)
            pose_start_b, _ = _pose_at_s(geoms_b, 0.0)
            dx = pose_start_b.x - pose_end_a.x
            dy = pose_start_b.y - pose_end_a.y
            dxy = math.hypot(dx, dy)
            dhdg = abs(_angle_diff(pose_start_b.hdg, pose_end_a.hdg))
            if dxy > eps_xy or dhdg > eps_hdg:
                bad.append((rid, eid, kind, dxy, dhdg))
    return bad


class TestNaiveCheckerIsWrong:
    """RED evidence: the pre-fix (naive) comparison flags fixtures that are
    actually geometrically continuous once link_kind + contactPoint are
    honored."""

    def test_naive_flags_predecessor_end_contact_as_discontinuous(self, tmp_path):
        # Naive always compares A.end -> B.start regardless of link_kind, but
        # this link is a PREDECESSOR (should anchor at road 2's START, s=0),
        # not road 2's end. Road 2 only has one geometry (length=5), so its
        # "end" pose (s=5) differs in position from its "start" pose (s=0)
        # -- the naive comparison lands on the wrong point entirely.
        xodr = _write_xodr(tmp_path, _predecessor_end_contact_body())
        bad = _naive_link_check(xodr)
        assert len(bad) == 1, "naive checker should (incorrectly) flag this predecessor/end-contact join"
        rid, eid, kind, dxy, dhdg = bad[0]
        assert dxy > 0.05

    def test_naive_flags_successor_end_contact_anti_parallel_as_discontinuous(self, tmp_path):
        xodr = _write_xodr(tmp_path, _successor_end_contact_anti_parallel_body())
        bad = _naive_link_check(xodr)
        assert len(bad) == 1, "naive checker should (incorrectly) flag this anti-parallel end-contact join"
        rid, eid, kind, dxy, dhdg = bad[0]
        # Naive compares raw headings without the anti-parallel correction,
        # so it reports a large heading delta (~pi) here even though this
        # join is geometrically valid by design.
        assert dhdg == pytest.approx(math.pi, abs=1e-6)

    def test_naive_passes_successor_start_contact(self, tmp_path):
        # This one happens to be naive-compatible (A.end -> B.start is the
        # correct comparison for a plain successor/start-contact link), so
        # it is a control showing the naive checker is not ALWAYS wrong.
        xodr = _write_xodr(tmp_path, _successor_start_contact_body())
        bad = _naive_link_check(xodr)
        assert bad == []

    def test_naive_flags_negative_control_5m_gap(self, tmp_path):
        xodr = _write_xodr(tmp_path, _negative_control_5m_gap_body())
        bad = _naive_link_check(xodr)
        assert len(bad) == 1
        assert bad[0][3] == pytest.approx(5.0, abs=1e-6)


class TestCorrectedCheckerHonorsLinkKindAndContactPoint:
    """GREEN evidence: the corrected check_geometric_continuity() in
    ultimate_pipeline/quality/check_geometric_continuity.py honors
    link_kind + contactPoint and no longer false-positives on these
    fixtures."""

    def test_predecessor_end_contact_colinear_passes(self, tmp_path):
        xodr = _write_xodr(tmp_path, _predecessor_end_contact_body())
        report = check_geometric_continuity(xodr)
        assert report["ok"] is True
        assert report["num_issues"] == 0

    def test_successor_end_contact_anti_parallel_passes(self, tmp_path):
        xodr = _write_xodr(tmp_path, _successor_end_contact_anti_parallel_body())
        report = check_geometric_continuity(xodr)
        assert report["ok"] is True
        assert report["num_issues"] == 0

    def test_successor_start_contact_colinear_passes(self, tmp_path):
        xodr = _write_xodr(tmp_path, _successor_start_contact_body())
        report = check_geometric_continuity(xodr)
        assert report["ok"] is True
        assert report["num_issues"] == 0

    def test_negative_control_5m_gap_still_fails(self, tmp_path):
        """The 5 m negative-control fixture MUST still fail under the
        corrected checker. Honoring contactPoint must never weaken the
        checker into passing a genuine gap."""
        xodr = _write_xodr(tmp_path, _negative_control_5m_gap_body())
        report = check_geometric_continuity(xodr)
        assert report["ok"] is False
        assert report["num_issues"] == 1
        assert report["issues"][0]["dxy"] == pytest.approx(5.0, abs=1e-6)


class TestJunctionConnectingRoadLaneOffset:
    """Junction connecting roads (`junction != "-1"`) meet the incoming road
    at a lane boundary offset from the reference line by ~lane_width.
    Reference-line coincidence is the wrong continuity measure for them, so
    the corrected checker classifies these as diagnostic
    `junction_connector_issues`, never as hard `issues`. This matches
    option (b) from the spec: exclude junction-internal road-to-road
    reference-line checks from the hard-fail gate; report them as
    diagnostic evidence instead."""

    def test_junction_connector_lane_offset_is_diagnostic_not_hard_fail(self, tmp_path):
        body = (
            '<road id="1" length="10" junction="-1">'
            '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
            "</road>"
            '<road id="100" length="5" junction="10">'
            '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
            '<planView><geometry s="0" x="10" y="3.5" hdg="0" length="5"><line/></geometry></planView>'
            "</road>"
            '<junction id="10">'
            '<connection id="0" incomingRoad="1" connectingRoad="100" contactPoint="start">'
            '<laneLink from="-1" to="-1"/>'
            "</connection>"
            "</junction>"
        )
        xodr = _write_xodr(tmp_path, body)
        report = check_geometric_continuity(xodr)
        # A one-lane-width (3.5 m) offset at a junction connector boundary
        # is expected CARLA junction-routing geometry, not a hard failure.
        assert report["ok"] is True
        assert report["num_issues"] == 0
        assert report["num_junction_connector_issues"] == 1
        assert report["junction_connector_issues"][0]["dxy"] == pytest.approx(3.5)

    def test_junction_connector_genuine_gap_still_flagged_as_diagnostic_outlier(self, tmp_path):
        # Even in the diagnostic bucket, a genuinely large residual (well
        # beyond a multi-lane offset) should still show up so it can be
        # triaged -- it just should not hard-fail the generic gate.
        body = (
            '<road id="1" length="10" junction="-1">'
            '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
            "</road>"
            '<road id="100" length="5" junction="10">'
            '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
            '<planView><geometry s="0" x="10" y="50.0" hdg="0" length="5"><line/></geometry></planView>'
            "</road>"
            '<junction id="10">'
            '<connection id="0" incomingRoad="1" connectingRoad="100" contactPoint="start">'
            '<laneLink from="-1" to="-1"/>'
            "</connection>"
            "</junction>"
        )
        xodr = _write_xodr(tmp_path, body)
        report = check_geometric_continuity(xodr)
        assert report["ok"] is True  # still not a hard fail (junction-internal)
        assert report["num_junction_connector_issues"] == 1
        assert report["junction_connector_issues"][0]["dxy"] == pytest.approx(50.0)
