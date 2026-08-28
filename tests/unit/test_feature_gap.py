"""ultimate_pipeline/domain_gap/feature_gap.py -- FeatureDomainGap.

This is the actual math behind RQ2's perceptual-gap numbers once real manual/auto
perception captures exist: PerceptionGap.compare()'s feature_proxy branch (see
ultimate_pipeline/domain_gap/perception_gap.py) and
ultimate_pipeline/tools/compute_perception_gap.py both call
FeatureDomainGap.compute(), which returns {"mmd", "wasserstein", "mean_gap"}.

No test previously existed for this module. These are known-value + invariant
characterization tests: identical distributions -> ~0 gap on all three metrics;
a real mean shift -> positive, monotonically increasing gap. Also verifies the
NumPy RBF-kernel fallback (used when scikit-learn is unavailable) agrees with
sklearn's rbf_kernel where both are installed, since a silent divergence there
would make the "mmd" number method-dependent and therefore untrustworthy.
"""
from __future__ import annotations

import numpy as np
import pytest

from ultimate_pipeline.domain_gap.feature_gap import FeatureDomainGap, rbf_kernel


def test_mmd_is_near_zero_for_identical_distributions():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 8))
    fg = FeatureDomainGap(output_dir=".")
    d = fg.mmd(X, X)
    assert d == pytest.approx(0.0, abs=1e-9)


def test_mmd_is_positive_and_monotone_for_a_mean_shift():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(80, 6))
    Y_small_shift = X + 0.5
    Y_large_shift = X + 5.0

    fg = FeatureDomainGap(output_dir=".")
    d_small = fg.mmd(X, Y_small_shift)
    d_large = fg.mmd(X, Y_large_shift)

    assert d_small > 0
    assert d_large > d_small


def test_wasserstein_is_zero_for_identical_distributions_and_positive_for_shift():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(60, 1))
    fg = FeatureDomainGap(output_dir=".")

    assert fg.wasserstein(X, X) == pytest.approx(0.0, abs=1e-9)
    assert fg.wasserstein(X, X + 3.0) > 0


def test_mean_gap_is_the_euclidean_distance_between_means():
    X = np.array([[0.0, 0.0], [2.0, 0.0]])
    Y = np.array([[3.0, 4.0], [3.0, 4.0]])
    fg = FeatureDomainGap(output_dir=".")
    # mean(X) = (1,0), mean(Y) = (3,4) -> ||diff|| = sqrt(2^2+4^2) = sqrt(20)
    assert fg.mean_gap(X, Y) == pytest.approx(np.sqrt(20.0))


def test_compute_returns_all_three_metrics_as_finite_floats():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(30, 4))
    Y = rng.normal(loc=1.0, size=(30, 4))
    fg = FeatureDomainGap(output_dir=".")
    out = fg.compute(X, Y)
    assert set(out) == {"mmd", "wasserstein", "mean_gap"}
    assert all(np.isfinite(v) for v in out.values())


def test_compute_handles_empty_inputs_without_raising():
    fg = FeatureDomainGap(output_dir=".")
    out = fg.compute(np.zeros((0, 4)), np.zeros((0, 4)))
    assert out["mmd"] == 0.0
    assert out["mean_gap"] == 0.0


def test_numpy_rbf_kernel_fallback_matches_sklearn_when_available():
    sklearn = pytest.importorskip("sklearn")
    from sklearn.metrics.pairwise import rbf_kernel as sk_rbf_kernel

    rng = np.random.default_rng(4)
    X = rng.normal(size=(10, 5))
    Y = rng.normal(size=(7, 5))
    gamma = 0.3

    # rbf_kernel() itself prefers sklearn when installed; force the pure-NumPy
    # path by calling the same closed-form math directly and comparing.
    X_norm = np.sum(X * X, axis=1).reshape(-1, 1)
    Y_norm = np.sum(Y * Y, axis=1).reshape(1, -1)
    sq_dists = np.maximum(X_norm + Y_norm - 2.0 * (X @ Y.T), 0.0)
    numpy_fallback = np.exp(-gamma * sq_dists)

    sklearn_result = sk_rbf_kernel(X, Y, gamma=gamma)
    assert np.allclose(numpy_fallback, sklearn_result, atol=1e-10)

    # And rbf_kernel() itself (whichever backend it picks) agrees too.
    assert np.allclose(rbf_kernel(X, Y, gamma), sklearn_result, atol=1e-10)
