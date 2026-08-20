"""RQ1 needs DomainGapAnalyzer.compare_xodr_to_xodr (manual XODR vs auto XODR).
It was an unimplemented `pass` stub returning None, so ManualAutoComparator.compare_maps
crashed. This locks the XODR<->XODR structural-gap contract (mirrors .compare)."""
from types import SimpleNamespace

from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer, DomainGapScores


def _stats(**kw):
    d = dict(
        avg_lane_width=3.5,
        curvature_samples=[],
        total_road_length=1000.0,
        num_traffic_lights=0,
        num_buildings=0,
        road_type_counts={},
    )
    d.update(kw)
    return SimpleNamespace(**d)


def test_xodr_to_xodr_returns_scores_not_none():
    scores = DomainGapAnalyzer.compare_xodr_to_xodr(
        reference_stats=_stats(), generated_stats=_stats()
    )
    assert scores is not None
    assert isinstance(scores, DomainGapScores)


def test_xodr_to_xodr_identical_is_zero_gap():
    s = _stats(avg_lane_width=3.5, total_road_length=1000.0, num_traffic_lights=10, num_buildings=100)
    scores = DomainGapAnalyzer.compare_xodr_to_xodr(reference_stats=s, generated_stats=s)
    assert scores.road_length_gap == 0.0
    assert scores.lane_width_gap == 0.0
    assert scores.traffic_light_density_gap == 0.0


def test_xodr_to_xodr_scope_gap_caps_at_one():
    # manual (reference) 53.5 km vs auto (generated) 1495 km -> huge coverage gap, capped at 1.0
    ref = _stats(total_road_length=53525.0, avg_lane_width=3.65)
    gen = _stats(total_road_length=1495647.0, avg_lane_width=3.5)
    scores = DomainGapAnalyzer.compare_xodr_to_xodr(reference_stats=ref, generated_stats=gen)
    assert scores.road_length_gap == 1.0
    assert scores.lane_width_gap > 0.0


def test_xodr_to_xodr_symmetry_of_reference_role():
    # reference is ground truth: swapping changes the length ratio denominator
    a = _stats(total_road_length=1000.0)
    b = _stats(total_road_length=2000.0)
    s_ab = DomainGapAnalyzer.compare_xodr_to_xodr(reference_stats=a, generated_stats=b)
    assert s_ab.road_length_gap == 1.0  # |1 - 2000/1000| = 1.0
