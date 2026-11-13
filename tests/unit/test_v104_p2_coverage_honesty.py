"""V104 P2 — regression tests for the directional-coverage honesty fix.

The defect these tests pin:

  The coverage report mixed two DIFFERENT populations in one ``counts``
  block.  ``matched`` / ``authoritative`` count XODR ROADS; the
  ``correspondence_*`` / ``ambiguous_correspondence`` /
  ``unmatched_correspondence`` counts count OSM WAYS.  Reading "44 of 3057
  roads matched" divided an XODR-road numerator by an OSM-way denominator
  and produced a meaningless "1.4%" that was nonetheless reported as
  ``coverage PASS``.

  The fix states both populations, measures every rate against the
  population its numerator belongs to, and separates the CONTRACT verdict
  (``status``: does authoritative directional evidence exist) from the
  ADEQUACY verdict (``coverage_qualification``: is the coverage good
  enough, which is unknowable until a minimum is declared).

Each test below is a NEGATIVE control: it fails on the pre-fix code.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.enrichment.osm_direction import (
    DIRECTION_KEY,
    MATCH_CLASS_KEY,
    MATCH_CONFIDENCE_KEY,
    directional_coverage_report,
)


def _road(
    orientation: str = "forward",
    match_class: str = "EXACT",
    confidence: str = "0.95",
    lanes: str = "2",
    oneway: str = "yes",
) -> dict:
    return {
        DIRECTION_KEY: orientation,
        MATCH_CLASS_KEY: match_class,
        MATCH_CONFIDENCE_KEY: confidence,
        "lanes": lanes,
        "oneway": oneway,
    }


# ---------------------------------------------------------------------------
# The populations must be stated, not conflated
# ---------------------------------------------------------------------------

def test_p2_report_states_both_populations_separately():
    """The two denominators are named and counted."""
    report = directional_coverage_report(
        {"1": _road()},
        source_available=True,
        match_class_counts={"EXACT": 0, "HIGH": 68, "AMBIGUOUS": 246, "UNMATCHED": 2743},
        xodr_road_count=993,
    )

    population = report["population"]
    assert population["xodr_road_count"] == 993
    assert population["osm_way_count"] == 3057
    assert "matched_road_rate_percent" in population["xodr_road_count_note"]
    assert "NOT a road denominator" in population["osm_way_count_note"]


def test_p2_road_rate_is_measured_against_roads_not_ways():
    """The road-level rate divides roads by roads.

    Before the fix there was no road denominator at all, so the only
    available "rate" was 44/3057 -- a road numerator over a way
    denominator.
    """
    report = directional_coverage_report(
        {str(i): _road() for i in range(44)},
        source_available=True,
        match_class_counts={"EXACT": 0, "HIGH": 68, "AMBIGUOUS": 246, "UNMATCHED": 2743},
        xodr_road_count=993,
    )

    rates = report["rates"]
    # 44 roads out of 993 roads.
    assert rates["matched_road_rate_percent"] == pytest.approx(
        100.0 * 44 / 993, abs=1e-3
    )
    # 68 ways out of 3057 ways.
    assert rates["matched_way_rate_percent"] == pytest.approx(
        100.0 * 68 / 3057, abs=1e-3
    )
    # The two rates are NOT equal -- which is exactly the confusion: the
    # old headline divided 44 roads by 3057 ways.
    assert rates["matched_road_rate_percent"] != rates["matched_way_rate_percent"]
    assert report["rates"]["matched_road_count"] == 44
    assert report["rates"]["matched_way_count"] == 68


def test_p2_no_road_denominator_yields_no_rate_rather_than_a_wrong_one():
    """Without the road population the rate is None, never a wrong number."""
    report = directional_coverage_report(
        {"1": _road()},
        source_available=True,
        match_class_counts={"EXACT": 0, "HIGH": 68, "AMBIGUOUS": 246, "UNMATCHED": 2743},
    )

    assert report["population"]["xodr_road_count"] is None
    assert report["rates"]["matched_road_rate_percent"] is None
    assert report["rates"]["authoritative_road_rate_percent"] is None
    # The way-level rate is still computable and correct.
    assert report["rates"]["matched_way_rate_percent"] == pytest.approx(
        100.0 * 68 / 3057, abs=1e-3
    )


# ---------------------------------------------------------------------------
# The adequacy verdict is separate from the contract verdict
# ---------------------------------------------------------------------------

def test_p2_pass_without_a_declared_threshold_is_not_an_adequacy_pass():
    """A PASS may not be read as 'the coverage is adequate'.

    Before the fix, a report with 35 authoritative roads out of 3057
    source ways was ``status: PASS`` with nothing in it to stop a reader
    concluding the coverage was fine.
    """
    report = directional_coverage_report(
        {"1": _road()},
        source_available=True,
        xodr_road_count=32267,
    )

    assert report["status"] == "PASS"
    qualification = report["coverage_qualification"]
    assert qualification["status"] == "UNDECLARED_THRESHOLD"
    assert qualification["reason"] == "no_declared_minimum_authoritative_rate"
    assert qualification["minimum_authoritative_rate_percent"] is None
    assert "must not be read as" in qualification["note"]


def test_p2_declared_threshold_below_the_measured_rate_is_below_minimum():
    report = directional_coverage_report(
        {"1": _road()},
        source_available=True,
        xodr_road_count=32267,
        minimum_authoritative_rate_percent=1.0,
    )

    qualification = report["coverage_qualification"]
    assert qualification["status"] == "BELOW_MINIMUM"
    assert "authoritative_rate_below_minimum" in qualification["reason"]
    assert qualification["minimum_authoritative_rate_percent"] == 1.0


def test_p2_declared_threshold_above_the_measured_rate_meets_minimum():
    report = directional_coverage_report(
        {str(i): _road() for i in range(10)},
        source_available=True,
        xodr_road_count=100,
        minimum_authoritative_rate_percent=5.0,
    )

    assert report["status"] == "PASS"
    assert report["rates"]["authoritative_road_rate_percent"] == pytest.approx(10.0)
    qualification = report["coverage_qualification"]
    assert qualification["status"] == "MEETS_MINIMUM"
    assert qualification["reason"] == ""


def test_p2_declared_threshold_with_no_road_population_stays_undeclared():
    """A threshold cannot be evaluated without the denominator."""
    report = directional_coverage_report(
        {"1": _road()},
        source_available=True,
        minimum_authoritative_rate_percent=1.0,
    )

    qualification = report["coverage_qualification"]
    assert qualification["status"] == "UNDECLARED_THRESHOLD"
    assert qualification["minimum_authoritative_rate_percent"] == 1.0


# ---------------------------------------------------------------------------
# The contract verdict itself must not regress
# ---------------------------------------------------------------------------

def test_p2_contract_verdict_is_unchanged_by_the_adequacy_verdict():
    """The contract rules still hold, and they are what ``status`` means."""
    missing = directional_coverage_report({}, source_available=False)
    assert missing["status"] == "BLOCKED_INPUT"

    no_match = directional_coverage_report({}, source_available=True)
    assert no_match["status"] == "BLOCKED_INPUT"

    not_authoritative = directional_coverage_report(
        {"1": _road(orientation="unknown")},
        source_available=True,
    )
    assert not_authoritative["status"] == "INCOMPLETE"

    authoritative = directional_coverage_report(
        {"1": _road()},
        source_available=True,
    )
    assert authoritative["status"] == "PASS"
    # ... and the contract PASS says nothing about adequacy.
    assert authoritative["coverage_qualification"]["status"] == "UNDECLARED_THRESHOLD"


def test_p2_qualification_never_overrides_the_contract_verdict():
    """A declared minimum that is met must not turn INCOMPLETE into PASS."""
    report = directional_coverage_report(
        {"1": _road(orientation="unknown")},
        source_available=True,
        xodr_road_count=100,
        minimum_authoritative_rate_percent=0.0,
    )

    assert report["status"] == "INCOMPLETE"
    assert report["coverage_qualification"]["status"] == "MEETS_MINIMUM"
