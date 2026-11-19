"""V106-O2 -- the documented O2 gaps, closed.

These are the three gaps the V103-O2 handoff stated as open, each now
closed with a test that fails without the fix:

1. a via-WAY restriction names a movement that is NOT a shared-node
   movement, so it must be evaluated as its own movement class;
2. ``no_u_turn`` forbids a SELF-movement that the node-based candidate
   set never contains, so without explicit handling a parsed ``no_u_turn``
   would be reported as applied while changing nothing;
3. a conditional restriction needs a clock context, and with one the
   restriction must become decidable rather than permanently
   ``UNSUPPORTED_CONDITIONAL``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from ultimate_pipeline.enrichment.osm_legal_movement import (
    MovementStatus,
    build_allowed_movement_report,
    build_movement_graph,
)
from ultimate_pipeline.enrichment.osm_restrictions import (
    RestrictionContext,
    evaluate_conditional,
    parse_restrictions,
    read_osm_document,
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "map.osm"
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. The via-WAY chain
# ---------------------------------------------------------------------------


def test_o2_a_via_way_restriction_is_evaluated_as_its_own_movement(tmp_path):
    """from 10, along via-way 13, to 11 -- a movement no node pair describes."""
    path = _write(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/><node id="4" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="13"><nd ref="2"/><nd ref="3"/></way>
          <way id="11"><nd ref="3"/><nd ref="4"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="way" ref="13" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
          </relation>
        </osm>
        """,
    )
    document = read_osm_document(path)
    report = build_allowed_movement_report(build_movement_graph(document))

    records = [m for m in report.movements if m.via_ways]
    assert records, "the via-way restriction produced no movement record"
    record = records[0]
    assert record.from_way == "10"
    assert record.to_way == "11"
    assert record.via_ways == ("13",)
    assert record.status == MovementStatus.DENY_SOURCE_PROVEN.value
    assert record.rule_source == "osm_no_restriction"


def test_o2_a_via_way_restriction_that_does_not_connect_is_not_a_denial(tmp_path):
    """A via-way that does not connect the two ways forbids nothing."""
    path = _write(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/><node id="9" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="13"><nd ref="9"/><nd ref="3"/></way>
          <way id="11"><nd ref="3"/><nd ref="4"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="way" ref="13" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
          </relation>
        </osm>
        """,
    )
    document = read_osm_document(path)
    report = build_allowed_movement_report(build_movement_graph(document))

    records = [m for m in report.movements if m.via_ways]
    assert records
    assert records[0].status == MovementStatus.UNKNOWN_NO_SOURCE.value
    assert "does not exist" in records[0].reason


# ---------------------------------------------------------------------------
# 2. The no_u_turn semantics
# ---------------------------------------------------------------------------


def test_o2_a_no_u_turn_forbids_the_self_movement(tmp_path):
    """A no_u_turn names a movement the node-based candidate set excludes."""
    path = _write(
        tmp_path,
        """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="10" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_u_turn"/>
          </relation>
        </osm>
        """,
    )
    document = read_osm_document(path)
    report = build_allowed_movement_report(build_movement_graph(document))

    uturn = [
        m for m in report.movements if m.rule_source == "osm_no_restriction"
    ]
    assert uturn, "the no_u_turn produced no movement record"
    assert uturn[0].status == MovementStatus.DENY_SOURCE_PROVEN.value
    assert "no_u_turn" in uturn[0].reason


# ---------------------------------------------------------------------------
# 3. The conditional-restriction context
# ---------------------------------------------------------------------------


def test_o2_a_conditional_evaluation_returns_none_without_a_clock():
    assert evaluate_conditional("no @ (10:00-16:00)", RestrictionContext()) is None


def test_o2_a_conditional_evaluation_reads_a_daily_window():
    context = RestrictionContext(clock="12:00")
    assert evaluate_conditional("no @ (10:00-16:00)", context) is True
    assert evaluate_conditional("yes @ (10:00-16:00)", context) is False

    outside = RestrictionContext(clock="18:00")
    assert evaluate_conditional("no @ (10:00-16:00)", outside) is False
    assert evaluate_conditional("yes @ (10:00-16:00)", outside) is True


def test_o2_a_conditional_evaluation_reads_a_weekday_window():
    weekday = RestrictionContext(clock="08:00", day="Mo")
    assert evaluate_conditional("no @ (Mo-Fr 07:00-09:00)", weekday) is True
    # A MID-week day must also be inside the range: the range is resolved
    # by INDEX in the weekday sequence, not by a lexical comparison (which
    # would put "Mo" after "Fr").
    midweek = RestrictionContext(clock="08:00", day="We")
    assert evaluate_conditional("no @ (Mo-Fr 07:00-09:00)", midweek) is True
    weekend = RestrictionContext(clock="08:00", day="Su")
    assert evaluate_conditional("no @ (Mo-Fr 07:00-09:00)", weekend) is False


def test_o2_an_unsupported_condition_stays_undecidable():
    context = RestrictionContext(clock="12:00")
    # A dated range is not modelled and must never be guessed.
    assert evaluate_conditional("no @ (2026-01-01/2026-12-31)", context) is None


def test_o2_a_conditional_restriction_becomes_decidable_with_a_context(tmp_path):
    body = """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
            <tag k="restriction:conditional" v="no @ (10:00-16:00)"/>
          </relation>
        </osm>
    """
    path = _write(tmp_path, body)
    document = read_osm_document(path)

    without = parse_restrictions(document)
    assert len(without.undecidable()) == 1
    assert without.applicable() == ()

    inside = parse_restrictions(
        document, context=RestrictionContext(clock="12:00")
    )
    assert len(inside.applicable()) == 1
    assert inside.undecidable() == ()

    outside = parse_restrictions(
        document, context=RestrictionContext(clock="18:00")
    )
    # Outside the window the restriction does not apply, and that is
    # RECORDED rather than silently dropped.
    assert outside.applicable() == ()
    assert len(outside.restrictions) == 1
    assert outside.restrictions[0].status == "INCOMPLETE"
    assert "does not apply" in outside.restrictions[0].reason


def test_o2_the_graph_accepts_a_restriction_context(tmp_path):
    body = """
        <osm version="0.6" generator="test">
          <node id="1" lat="48" lon="11"/><node id="2" lat="48" lon="11"/>
          <node id="3" lat="48" lon="11"/>
          <way id="10"><nd ref="1"/><nd ref="2"/></way>
          <way id="11"><nd ref="2"/><nd ref="3"/></way>
          <relation id="100">
            <member type="way" ref="10" role="from"/>
            <member type="node" ref="2" role="via"/>
            <member type="way" ref="11" role="to"/>
            <tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/>
            <tag k="restriction:conditional" v="no @ (10:00-16:00)"/>
          </relation>
        </osm>
    """
    path = _write(tmp_path, body)
    document = read_osm_document(path)

    strict = build_allowed_movement_report(build_movement_graph(document))
    assert strict.undecidable_restrictions == 1

    decided = build_allowed_movement_report(
        build_movement_graph(
            document, restriction_context=RestrictionContext(clock="12:00")
        )
    )
    assert decided.undecidable_restrictions == 0
    denied = [m for m in decided.movements if m.rule_source == "osm_no_restriction"]
    assert denied
    assert denied[0].status == MovementStatus.DENY_SOURCE_PROVEN.value
