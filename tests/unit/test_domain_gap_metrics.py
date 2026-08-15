"""A3 — characterization tests for domain_gap metrics (untested subset).

Deterministic, offline. Focuses on the DomainGapAggregator's academic contract
(composite in [0,1], 0=identical, disabled/missing components never influence it)
plus untested pure helpers of topology_gap / geometry_gap. A failure here is a
discovered defect — escalate, don't loosen. XODR-path metrics
(structural/semantic/topology.compute) still need fixtures (see A3 report).
"""
from __future__ import annotations

from ultimate_pipeline.domain_gap.domain_gap_aggregator import DomainGapAggregator as Agg
from ultimate_pipeline.domain_gap.geometry_gap import _estimate_hausdorff_time, _safe_float
from ultimate_pipeline.domain_gap.topology_gap import _norm_diff, _safe_int


# ---- DomainGapAggregator: the composite contract --------------------------
def test_identical_maps_composite_is_zero():
    out = Agg.aggregate(
        gap_geometry={"rmse": 0.0}, gap_curvature={"kl_divergence": 0.0},
        compute_composite=True,
    )
    assert out["composite"] == 0.0  # 0 = identical maps


def test_composite_is_clamped_to_unit_range():
    out = Agg.aggregate(gap_geometry={"rmse": 1000.0}, compute_composite=True)
    assert out["composite"] == 1.0  # rmse_norm clamped to 1.0
    assert 0.0 <= out["composite"] <= 1.0


def test_disabled_component_excluded_from_composite():
    out = Agg.aggregate(
        gap_geometry={"disabled": True}, gap_curvature={"kl_divergence": 0.25},
        compute_composite=True,
    )
    assert out["components"]["geometry"] == {"disabled": True}
    assert out["composite"] == 0.5  # curvature only: _norm(0.25, 0.5) = 0.5
    assert out["composite_metadata"]["used_components"] == ["curvature"]


def test_no_normalized_components_yields_none_composite():
    out = Agg.aggregate(compute_composite=True)
    assert out["composite"] is None
    assert "reason" in out["composite_metadata"]


def test_semantic_and_elevation_reported_but_excluded_from_composite():
    out = Agg.aggregate(
        gap_geometry={"rmse": 0.5}, gap_semantic={"delta": 5}, gap_elevation={"x": 1},
        compute_composite=True,
    )
    assert out["components"]["semantic"] == {"delta": 5}
    assert out["components"]["elevation"] == {"x": 1}
    assert "semantic" not in out["composite_metadata"]["used_components"]
    assert "semantic" in out["composite_metadata"]["excluded_components"]


def test_norm_helper_clamps_and_returns_none_on_undefined():
    assert Agg._norm(100.0, 1.0) == 1.0
    assert abs(Agg._norm(0.3, 1.0) - 0.3) < 1e-9
    assert Agg._norm(None, 1.0) is None
    assert Agg._norm(0.5, 0.0) is None  # ref <= 0 undefined


# ---- untested pure helpers ------------------------------------------------
def test_topology_norm_diff():
    assert _norm_diff(10, 10) == 0.0
    assert _norm_diff(0, 5) == 1.0
    assert _norm_diff(5, 10) == 0.5
    assert _norm_diff(0, 0) == 0.0  # denom floored at 1


def test_topology_safe_int():
    assert _safe_int("5") == 5
    assert _safe_int("not-int", default=-1) == -1


def test_geometry_safe_float_and_hausdorff_estimate():
    assert _safe_float("3.5") == 3.5
    assert _safe_float(None, default=0.0) == 0.0
    assert _estimate_hausdorff_time(0) == 0.0
    assert _estimate_hausdorff_time(1000) > _estimate_hausdorff_time(100) > 0.0
