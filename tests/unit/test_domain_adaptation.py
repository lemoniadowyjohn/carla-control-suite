from __future__ import annotations

import numpy as np
import pytest

from ultimate_pipeline.domain_gap.adaptation.adaptation_runner import DomainAdaptation
from ultimate_pipeline.domain_gap.adaptation.coral import apply_coral
from ultimate_pipeline.domain_gap.adaptation.mmd import apply_mean_matching, apply_mmd
from ultimate_pipeline.experiments.thesis.core_algorithms import (
    apply_mean_matching as thesis_apply_mean_matching,
    apply_mmd as thesis_apply_mmd,
)


def _cov(x: np.ndarray) -> np.ndarray:
    return np.cov(np.asarray(x, dtype=np.float64), rowvar=False)


def test_coral_identical_source_target_is_near_noop():
    xs = np.array([[0.0, 1.0], [1.0, 2.0], [2.0, 4.0], [4.0, 8.0]], dtype=np.float64)

    xs_coral, xt = apply_coral(xs, xs)

    assert xs_coral.shape == xs.shape
    assert xt.shape == xs.shape
    assert np.allclose(xs_coral, xs, atol=1e-5)


def test_coral_aligns_source_covariance_to_target_covariance():
    rng = np.random.default_rng(42)
    base = rng.normal(size=(200, 2))
    xs = base @ np.array([[2.0, 0.2], [0.0, 0.5]]) + np.array([5.0, -2.0])
    xt = base @ np.array([[0.4, 0.1], [0.3, 1.5]]) + np.array([-1.0, 3.0])

    xs_coral, xt_out = apply_coral(xs, xt)

    assert xs_coral.shape == xs.shape
    assert xt_out.shape == xt.shape
    assert np.allclose(xs_coral.mean(axis=0), xt.mean(axis=0), atol=1e-5)
    assert np.allclose(_cov(xs_coral), _cov(xt), atol=1e-4)


def test_coral_is_finite_on_singular_covariance():
    xs = np.ones((8, 2), dtype=np.float64)
    xt = np.column_stack([np.arange(8, dtype=np.float64), np.ones(8)])

    xs_coral, xt_out = apply_coral(xs, xt)

    assert xs_coral.shape == xs.shape
    assert xt_out.shape == xt.shape
    assert np.isfinite(xs_coral).all()


def test_mean_matching_aligns_means_without_claiming_kernel_mmd():
    xs = np.array([[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], dtype=np.float64)
    xt = np.array([[10.0, -4.0], [11.0, -3.0], [12.0, -2.0]], dtype=np.float64)

    xs_mm, xt_out = apply_mean_matching(xs, xt)

    assert xs_mm.shape == xs.shape
    assert xt_out.shape == xt.shape
    assert np.allclose(xs_mm.mean(axis=0), xt.mean(axis=0))


def test_apply_mmd_compat_alias_warns_and_uses_mean_matching():
    xs = np.array([[0.0], [2.0]], dtype=np.float64)
    xt = np.array([[10.0], [12.0]], dtype=np.float64)

    with pytest.warns(DeprecationWarning, match="apply_mean_matching"):
        xs_alias, xt_alias = apply_mmd(xs, xt)
    xs_mm, xt_mm = apply_mean_matching(xs, xt)

    assert np.array_equal(xs_alias, xs_mm)
    assert np.array_equal(xt_alias, xt_mm)


def test_thesis_core_apply_mmd_compat_alias_warns_and_uses_mean_matching():
    xs = np.array([[0.0], [2.0]], dtype=np.float64)
    xt = np.array([[10.0], [12.0]], dtype=np.float64)

    with pytest.warns(DeprecationWarning, match="apply_mean_matching"):
        xs_alias, xt_alias = thesis_apply_mmd(xs, xt)
    xs_mm, xt_mm = thesis_apply_mean_matching(xs, xt)

    assert np.array_equal(xs_alias, xs_mm)
    assert np.array_equal(xt_alias, xt_mm)


def test_adaptation_runner_labels_mean_matching_not_mmd(monkeypatch):
    xs = np.column_stack([np.arange(20, dtype=np.float64), np.arange(20, dtype=np.float64) % 3])
    xt = xs + np.array([0.5, -0.25])
    labels = np.array([0, 1] * 10)
    monkeypatch.setattr(DomainAdaptation, "_eval", staticmethod(lambda Xs, ys, Xt, yt: float(np.asarray(Xs).shape[1])))

    results = DomainAdaptation().run(
        {"source": xs, "target": xt},
        {"source": labels, "target": labels},
    )

    methods = results["source"]["target"]
    assert set(methods) == {"baseline", "CORAL", "mean_matching"}
    assert "MMD" not in methods
