from __future__ import annotations

import math
from itertools import product

import pytest

from opendrive_geometry.primitives import evaluate_line, evaluate_arc
from tests.opendrive_geometry.adapters import (
    ALL_ADAPTERS,
    NON_BUGGY_ADAPTERS,
    ADAPTER_MAP_PLOTTER,
    ADAPTER_MAP_DIFF,
    EvalResult,
    Adapter,
)
from tests.opendrive_geometry.analytical import line_pose_at, arc_pose_at
from tests.opendrive_geometry.fixtures import (
    LINE_START,
    LINE_NONZERO_ORIGIN,
    LINE_ANGLED,
    ARC_QUARTER_CIRCLE_LEFT,
    ARC_QUARTER_CIRCLE_RIGHT,
    ARC_HALF_CIRCLE_LEFT,
    ARC_GENTLE_LEFT,
    ARC_GENTLE_RIGHT,
    ARC_NONZERO_ORIGIN,
    ARC_NONZERO_HDG,
    ARC_TIGHT,
    ARC_NEAR_ZERO_POS,
    ARC_NEAR_ZERO_NEG,
    ARC_AT_EPS_BOUNDARY,
    ARC_EXACT_ZERO,
)


def _check_match(
    adapter: Adapter,
    actual: EvalResult,
    fx,
    s: float,
    tol: float = 1e-8,
):
    if fx.curvature is not None and abs(fx.curvature) >= 1e-15:
        expected = arc_pose_at(fx, s)
    else:
        expected = line_pose_at(fx, s)
    msg = f"{adapter.name}: s={s}"
    assert abs(actual.x - expected.x) < tol, f"{msg} x: {actual.x} != {expected.x}"
    assert abs(actual.y - expected.y) < tol, f"{msg} y: {actual.y} != {expected.y}"
    assert abs(actual.hdg - expected.hdg) < tol, f"{msg} hdg: {actual.hdg} != {expected.hdg}"


# ---------------------------------------------------------------------------
# Line tests against all non-buggy implementations
# ---------------------------------------------------------------------------
LINE_FIXTURES = [
    (LINE_START, [0.0, 25.0, 50.0, 100.0]),
    (LINE_NONZERO_ORIGIN, [0.0, 25.0, 50.0]),
    (LINE_ANGLED, [0.0, 50.0, 100.0]),
]


class TestAllImplementationsLine:
    @pytest.mark.parametrize(
        "adapter,fx,ss",
        [
            (a, fx, s)
            for a in NON_BUGGY_ADAPTERS
            for fx, ss_list in LINE_FIXTURES
            for s in ss_list
        ],
    )
    def test_line_pose(self, adapter, fx, ss):
        result = adapter.evaluate(fx.x, fx.y, fx.hdg, fx.length, fx.curvature or 0.0, ss)
        _check_match(adapter, result, fx, ss)


# ---------------------------------------------------------------------------
# Arc tests against all non-buggy implementations
# ---------------------------------------------------------------------------
ARC_FIXTURES = [
    (ARC_QUARTER_CIRCLE_LEFT, [0.0, ARC_QUARTER_CIRCLE_LEFT.length / 2, ARC_QUARTER_CIRCLE_LEFT.length]),
    (ARC_QUARTER_CIRCLE_RIGHT, [0.0, ARC_QUARTER_CIRCLE_RIGHT.length / 2, ARC_QUARTER_CIRCLE_RIGHT.length]),
    (ARC_HALF_CIRCLE_LEFT, [0.0, ARC_HALF_CIRCLE_LEFT.length / 2, ARC_HALF_CIRCLE_LEFT.length]),
    (ARC_GENTLE_LEFT, [0.0, 50.0, 100.0]),
    (ARC_GENTLE_RIGHT, [0.0, 50.0, 100.0]),
    (ARC_NONZERO_ORIGIN, [0.0, 30.0, 60.0]),
    (ARC_NONZERO_HDG, [0.0, 40.0, 80.0]),
    (ARC_TIGHT, [0.0, 15.0, 30.0]),
]


class TestAllImplementationsArc:
    @pytest.mark.parametrize(
        "adapter,fx,ss",
        [
            (a, fx, s)
            for a in NON_BUGGY_ADAPTERS
            for fx, ss_list in ARC_FIXTURES
            for s in ss_list
        ],
    )
    def test_arc_pose(self, adapter, fx, ss):
        result = adapter.evaluate(fx.x, fx.y, fx.hdg, fx.length, fx.curvature, ss)
        _check_match(adapter, result, fx, ss)


# ---------------------------------------------------------------------------
# Edge-case arc values
# ---------------------------------------------------------------------------
EDGE_ARC_FIXTURES = [
    (ARC_NEAR_ZERO_POS, [50.0, 100.0]),
    (ARC_NEAR_ZERO_NEG, [50.0, 100.0]),
    (ARC_AT_EPS_BOUNDARY, [50.0, 100.0]),
    (ARC_EXACT_ZERO, [0.0, 50.0, 100.0]),
]


class TestAllImplementationsArcEdgeCases:
    @pytest.mark.parametrize(
        "adapter,fx,ss",
        [
            (a, fx, s)
            for a in NON_BUGGY_ADAPTERS
            for fx, ss_list in EDGE_ARC_FIXTURES
            for s in ss_list
        ],
    )
    def test_arc_edge(self, adapter, fx, ss):
        result = adapter.evaluate(fx.x, fx.y, fx.hdg, fx.length, fx.curvature or 0.0, ss)
        _check_match(adapter, result, fx, ss, tol=1e-6)


# ---------------------------------------------------------------------------
# Cross-comparison: assert all non-buggy adapters agree at endpoints
# ---------------------------------------------------------------------------
def _check_pairwise_agreement(adapter_a: Adapter, adapter_b: Adapter, fx, s: float, tol: float = 1e-10):
    ra = adapter_a.evaluate(fx.x, fx.y, fx.hdg, fx.length, fx.curvature or 0.0, s)
    rb = adapter_b.evaluate(fx.x, fx.y, fx.hdg, fx.length, fx.curvature or 0.0, s)
    msg = f"{adapter_a.name} vs {adapter_b.name} at s={s} of {fx}"
    assert abs(ra.x - rb.x) < tol, f"{msg} x: {ra.x} != {rb.x}"
    assert abs(ra.y - rb.y) < tol, f"{msg} y: {ra.y} != {rb.y}"
    assert abs(ra.hdg - rb.hdg) < tol, f"{msg} hdg: {ra.hdg} != {rb.hdg}"


PAIRWISE_FIXTURES = [
    (LINE_START, [0.0, 100.0]),
    (LINE_NONZERO_ORIGIN, [0.0, 50.0]),
    (ARC_QUARTER_CIRCLE_LEFT, [0.0, ARC_QUARTER_CIRCLE_LEFT.length]),
    (ARC_GENTLE_LEFT, [0.0, 100.0]),
    (ARC_NONZERO_ORIGIN, [0.0, 60.0]),
    (ARC_EXACT_ZERO, [0.0, 100.0]),
]


class TestCrossComparison:
    @pytest.mark.parametrize(
        "fixture_index",
        range(len(PAIRWISE_FIXTURES)),
    )
    @pytest.mark.parametrize(
        "pair",
        list(product(NON_BUGGY_ADAPTERS, NON_BUGGY_ADAPTERS)),
    )
    def test_adjacent_adapters_agree(self, pair, fixture_index):
        fx, ss_list = PAIRWISE_FIXTURES[fixture_index]
        a, b = pair
        if a is b:
            pytest.skip("same adapter")
        for s in ss_list:
            _check_pairwise_agreement(a, b, fx, s)


class TestMapPlotterNoBugs:
    """map_plotter adapter now matches correct implementation (line fallback at 1e-12)."""

    def test_line_endpoint_correct(self):
        result = ADAPTER_MAP_PLOTTER.evaluate(1.0, 2.0, 0.3, 100.0, 0.0, 100.0)
        expected = evaluate_line(1.0, 2.0, 0.3, 100.0, 100.0)
        assert abs(result.x - expected.x) < 1e-9
        assert abs(result.y - expected.y) < 1e-9

    def test_zero_curvature_arc_falls_back_to_line(self):
        result = ADAPTER_MAP_PLOTTER.evaluate(1.0, 2.0, 0.3, 100.0, 0.0, 100.0)
        expected = evaluate_line(1.0, 2.0, 0.3, 100.0, 100.0)
        assert abs(result.x - expected.x) < 1e-9
        assert abs(result.y - expected.y) < 1e-9

    def test_tiny_curvature_falls_back_to_line(self):
        result = ADAPTER_MAP_PLOTTER.evaluate(0.0, 0.0, 0.0, 100.0, 1e-15, 100.0)
        expected = evaluate_line(0.0, 0.0, 0.0, 100.0, 100.0)
        assert abs(result.x - expected.x) < 1e-9
        assert abs(result.y - expected.y) < 1e-9

    def test_arc_endpoint_correct(self):
        result = ADAPTER_MAP_PLOTTER.evaluate(0.0, 0.0, 0.0, 100.0, 0.01, 100.0)
        expected = evaluate_arc(0.0, 0.0, 0.0, 100.0, 0.01, 100.0)
        assert abs(result.x - expected.x) < 1e-9
        assert abs(result.y - expected.y) < 1e-9


class TestMapDiffNoBugs:
    """map_diff adapter now matches correct implementation (line fallback at 1e-12)."""

    def test_positive_curvature_heading_correct(self):
        result = ADAPTER_MAP_DIFF.evaluate(0.0, 0.0, 0.0, 100.0, 0.01, 100.0)
        expected = evaluate_arc(0.0, 0.0, 0.0, 100.0, 0.01, 100.0)
        assert abs(result.hdg - expected.hdg) < 1e-12

    def test_negative_curvature_heading_correct(self):
        result = ADAPTER_MAP_DIFF.evaluate(0.0, 0.0, 0.0, 100.0, -0.01, 100.0)
        expected = evaluate_arc(0.0, 0.0, 0.0, 100.0, -0.01, 100.0)
        assert abs(result.hdg - expected.hdg) < 1e-12

    def test_position_on_arc_correct(self):
        result = ADAPTER_MAP_DIFF.evaluate(0.0, 0.0, 0.0, 100.0, 0.01, 100.0)
        expected = evaluate_arc(0.0, 0.0, 0.0, 100.0, 0.01, 100.0)
        assert abs(result.x - expected.x) < 1e-9
        assert abs(result.y - expected.y) < 1e-9

    def test_nonzero_origin_negative_heading_correct(self):
        result = ADAPTER_MAP_DIFF.evaluate(10.0, 20.0, 0.5, 60.0, -0.02, 60.0)
        expected = evaluate_arc(10.0, 20.0, 0.5, 60.0, -0.02, 60.0)
        assert abs(result.hdg - expected.hdg) < 1e-12
        assert abs(result.x - expected.x) < 1e-9
        assert abs(result.y - expected.y) < 1e-9
