from types import SimpleNamespace

import pytest

from ultimate_pipeline.domain_gap.gap_analyzer import (
    DomainGapAnalyzer,
    _curvature_wasserstein_gap,
)


def _xodr_stats(**kw):
    data = dict(
        avg_lane_width=3.5,
        curvature_samples=[],
        total_road_length=1000.0,
        num_traffic_lights=0,
        num_buildings=0,
        road_type_counts={},
    )
    data.update(kw)
    return SimpleNamespace(**data)


def _osm_stats(**kw):
    data = dict(
        avg_lane_width=3.5,
        curvature_samples=[],
        total_road_length=1000.0,
        num_traffic_lights=0,
        num_buildings=0,
        road_type_counts={},
    )
    data.update(kw)
    return SimpleNamespace(**data)


def test_curvature_wasserstein_identical_distribution_is_zero():
    assert _curvature_wasserstein_gap([0.0, 0.02, -0.04], [0.0, 0.02, -0.04]) == 0.0


def test_curvature_wasserstein_shift_is_proportional_and_monotone():
    small = _curvature_wasserstein_gap([0.0, 0.0], [0.02, 0.02], scale_per_m=0.2)
    large = _curvature_wasserstein_gap([0.0, 0.0], [0.06, 0.06], scale_per_m=0.2)
    assert small == pytest.approx(0.1)
    assert large == pytest.approx(0.3)
    assert 0.0 < small < large < 1.0


def test_curvature_wasserstein_is_not_range_stretched_by_one_large_outlier():
    ref = [0.01] * 10_000
    gen = [0.02] * 10_000
    baseline = _curvature_wasserstein_gap(ref, gen, scale_per_m=0.2)
    with_one_outlier = _curvature_wasserstein_gap(ref + [37.0], gen, scale_per_m=0.2)
    assert baseline == pytest.approx(0.05)
    assert abs(with_one_outlier - baseline) < 0.02
    assert 0.0 <= with_one_outlier <= 1.0


def test_xodr_to_xodr_exposes_curvature_wasserstein_gap():
    scores = DomainGapAnalyzer.compare_xodr_to_xodr(
        reference_stats=_xodr_stats(curvature_samples=[0.0, 0.0]),
        generated_stats=_xodr_stats(curvature_samples=[0.02, 0.02]),
    )
    assert scores.curvature_wasserstein_gap == pytest.approx(0.1)
    assert scores.to_dict()["curvature_wasserstein_gap"] == pytest.approx(0.1)


def test_osm_to_xodr_exposes_curvature_wasserstein_gap():
    scores = DomainGapAnalyzer.compare(
        osm_stats=_osm_stats(curvature_samples=[0.0, 0.0]),
        xodr_stats=_xodr_stats(curvature_samples=[0.06, 0.06]),
    )
    assert scores.curvature_wasserstein_gap == pytest.approx(0.3)
