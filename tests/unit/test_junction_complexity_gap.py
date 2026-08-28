"""ultimate_pipeline/domain_gap/junction_complexity_gap.py -- compares junction
connection-count distributions (manual vs. auto-generated map) via a histogram + JS
divergence.

NOTE (verified 2026-08-28): despite the module's own docstring describing it as an
RQ1 structural-gap component, it is NOT actually invoked anywhere in
run_full_domain_gap.py or DomainGapAggregator.aggregate() -- the orchestrator only
carries a dead `JunctionComplexityGap = None` lazy-load placeholder that is never
reassigned. This module is exercised only by this test file, directly. Do not assume
its output reaches any thesis-reported number without re-verifying wiring first.

Pure, deterministic math (percentile interpolation, Jensen-Shannon divergence) that is
easy to get subtly wrong. Found untested via the orphaned-.pyc sweep.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.domain_gap.junction_complexity_gap import (
    JunctionComplexityGap,
    _hist,
    _js_divergence,
    _percentile,
    _stats,
)


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------

def test_percentile_empty_list_returns_zero():
    assert _percentile([], 0.5) == 0.0


def test_percentile_q_zero_returns_min():
    assert _percentile([1.0, 5.0, 9.0], 0.0) == 1.0


def test_percentile_q_one_returns_max():
    assert _percentile([1.0, 5.0, 9.0], 1.0) == 9.0


def test_percentile_median_odd_length_exact_element():
    assert _percentile([1.0, 3.0, 5.0], 0.5) == 3.0


def test_percentile_median_even_length_interpolates():
    # positions 0,1,2,3 -> pos = 3*0.5 = 1.5 -> interpolate between index 1 (2.0) and 2 (3.0)
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5


# ---------------------------------------------------------------------------
# _stats
# ---------------------------------------------------------------------------

def test_stats_empty_counts():
    assert _stats([]) == {"count": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}


def test_stats_basic_distribution():
    result = _stats([2, 4, 4, 4, 6])
    assert result["count"] == 5
    assert result["mean"] == 4.0
    assert result["median"] == 4.0
    assert result["max"] == 6.0


# ---------------------------------------------------------------------------
# _hist
# ---------------------------------------------------------------------------

def test_hist_counts_and_sorts_by_key():
    hist = _hist([3, 1, 3, 2, 1, 1])
    assert hist == {1: 3, 2: 1, 3: 2}
    assert list(hist.keys()) == [1, 2, 3]  # sorted ascending


def test_hist_empty_input():
    assert _hist([]) == {}


# ---------------------------------------------------------------------------
# _js_divergence
# ---------------------------------------------------------------------------

def test_js_divergence_identical_histograms_is_zero():
    hist = {2: 5, 3: 5}
    js = _js_divergence(hist, hist, epsilon=1e-6)
    assert abs(js) < 1e-9


def test_js_divergence_both_empty_is_zero():
    assert _js_divergence({}, {}, epsilon=1e-6) == 0.0


def test_js_divergence_is_symmetric():
    a = {2: 10, 3: 1}
    b = {2: 1, 3: 10}
    assert abs(_js_divergence(a, b, epsilon=1e-6) - _js_divergence(b, a, epsilon=1e-6)) < 1e-12


def test_js_divergence_disjoint_histograms_is_positive_and_bounded():
    # JS divergence (base-e) is bounded by ln(2) for fully disjoint distributions.
    a = {2: 10}
    b = {5: 10}
    js = _js_divergence(a, b, epsilon=1e-6)
    assert js > 0.0
    assert js <= math.log(2.0) + 1e-6


def test_js_divergence_more_different_distributions_score_higher():
    baseline = {2: 10}
    close = {2: 9, 3: 1}
    far = {2: 1, 3: 9}
    js_close = _js_divergence(baseline, close, epsilon=1e-6)
    js_far = _js_divergence(baseline, far, epsilon=1e-6)
    assert js_far > js_close


# ---------------------------------------------------------------------------
# JunctionComplexityGap -- end-to-end
# ---------------------------------------------------------------------------

def _xodr_with_junction_connection_counts(path: Path, counts) -> None:
    root = ET.Element("OpenDRIVE")
    for i, n in enumerate(counts):
        j = ET.SubElement(root, "junction", id=str(i))
        for c in range(n):
            ET.SubElement(j, "connection", id=str(c), incomingRoad="1", connectingRoad="2")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def test_compute_identical_maps_zero_divergence(tmp_path: Path):
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _xodr_with_junction_connection_counts(manual, [2, 3, 4])
    _xodr_with_junction_connection_counts(auto, [2, 3, 4])

    result = JunctionComplexityGap.compute(str(manual), str(auto))

    assert result["disabled"] is False
    assert "error" not in result
    assert abs(result["js_divergence"]) < 1e-9
    assert result["manual"]["stats"]["count"] == 3
    assert result["auto"]["stats"]["count"] == 3


def test_compute_different_maps_positive_divergence(tmp_path: Path):
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _xodr_with_junction_connection_counts(manual, [2, 2, 2])
    _xodr_with_junction_connection_counts(auto, [8, 8, 8])

    result = JunctionComplexityGap.compute(str(manual), str(auto))

    assert result["js_divergence"] > 0.0
    assert result["manual"]["histogram"] == {2: 3}
    assert result["auto"]["histogram"] == {8: 3}


def test_compute_missing_file_returns_error_not_raise(tmp_path: Path):
    result = JunctionComplexityGap.compute(str(tmp_path / "nope.xodr"), str(tmp_path / "also_nope.xodr"))
    # A failed compute() must be flagged disabled=True: callers key off "disabled" to
    # decide whether a component's gap value is trustworthy, and disabled=False here
    # would silently tell downstream aggregation/reporting the component succeeded
    # while "error" is populated and manual/auto stats are entirely absent.
    assert result["disabled"] is True
    assert "error" in result


def test_compare_is_an_alias_for_compute(tmp_path: Path):
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _xodr_with_junction_connection_counts(manual, [1, 2])
    _xodr_with_junction_connection_counts(auto, [1, 2])

    assert JunctionComplexityGap.compare(str(manual), str(auto)) == JunctionComplexityGap.compute(str(manual), str(auto))
