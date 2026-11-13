"""V104 P2 — behavioural fail-before proof.

The tests in ``test_v104_p2_coverage_honesty.py`` fail on the pre-fix code
with ``TypeError`` (the new keyword arguments do not exist yet).  That is a
valid fail-before, but it proves only that the API changed -- not that the
DEFECT was real.

These tests use only the PRE-EXISTING API, so they fail on the old code
because the old code is genuinely wrong, and pass on the fixed code
because the behaviour is now correct.  They are the behavioural proof that
the P2 finding was not invented.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.enrichment.osm_direction import (
    DIRECTION_KEY,
    MATCH_CLASS_KEY,
    MATCH_CONFIDENCE_KEY,
    directional_coverage_report,
)


def _road(orientation: str = "forward") -> dict:
    return {
        DIRECTION_KEY: orientation,
        MATCH_CLASS_KEY: "EXACT",
        MATCH_CONFIDENCE_KEY: "0.95",
        "lanes": "2",
        "oneway": "yes",
    }


def test_p2_pre_existing_api_exposes_the_road_rate():
    """The road-level rate must exist using only the old call signature.

    PRE-FIX: the report carried no rate at all.  The only way a reader
    could produce a "rate" was to divide the road count by the way count
    (44 roads / 3057 ways = "1.4%"), which is not a rate.

    POST-FIX: the report carries the road-level rate and names both
    populations.
    """
    report = directional_coverage_report(
        {str(i): _road() for i in range(44)},
        source_available=True,
        match_class_counts={"EXACT": 0, "HIGH": 68, "AMBIGUOUS": 246, "UNMATCHED": 2743},
    )

    # The populations must be stated.
    assert report["population"]["xodr_road_count"] is None
    assert report["population"]["osm_way_count"] == 3057

    # The way-level rate exists and is correct: 68 ways of 3057.
    assert report["rates"]["matched_way_rate_percent"] == pytest.approx(
        100.0 * 68 / 3057, abs=1e-3
    )

    # The road-level rate is None, NOT a wrong number.
    assert report["rates"]["matched_road_rate_percent"] is None


def test_p2_pre_existing_api_separates_adequacy_from_the_contract_verdict():
    """A PASS must not be readable as an adequacy verdict.

    PRE-FIX: the report said only ``status: PASS``.  With 35 authoritative
    roads out of 3057 source ways that is indistinguishable from a report
    where 99% of the map is covered.

    POST-FIX: the adequacy verdict is a separate, explicit block that is
    ``UNDECLARED_THRESHOLD`` until a minimum is declared.
    """
    report = directional_coverage_report(
        {"1": _road()},
        source_available=True,
        match_class_counts={"EXACT": 0, "HIGH": 68, "AMBIGUOUS": 246, "UNMATCHED": 2743},
    )

    assert report["status"] == "PASS"

    qualification = report["coverage_qualification"]
    assert qualification["status"] == "UNDECLARED_THRESHOLD"
    assert qualification["minimum_authoritative_rate_percent"] is None
    assert "must not be read as" in qualification["note"]


def test_p2_pre_existing_api_counts_the_way_population_from_the_class_counts():
    """The OSM-way population is the sum of the correspondence classes.

    PRE-FIX: nothing reported the way population, so a reader had to
    assume 3057 was the road count.

    POST-FIX: the way population is stated explicitly and is not
    presented as a road count.
    """
    report = directional_coverage_report(
        {},
        source_available=True,
        match_class_counts={"EXACT": 5, "HIGH": 89, "AMBIGUOUS": 1524, "UNMATCHED": 1439},
    )

    assert report["population"]["osm_way_count"] == 3057
    assert report["population"]["xodr_road_count"] is None
    assert report["rates"]["matched_way_rate_percent"] == pytest.approx(
        100.0 * 94 / 3057, abs=1e-3
    )
