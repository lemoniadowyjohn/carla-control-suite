"""RED/GREEN controls for feature-gap scientific missingness (FAL-A/FAL-04)."""
import numpy as np
import pytest

from ultimate_pipeline.domain_gap.feature_gap import FeatureDomainGap


@pytest.mark.parametrize("metric", ["mmd", "wasserstein", "mean_gap", "compute"])
@pytest.mark.parametrize("source,target", [([], [1, 2]), ([1, 2], []), ([], [])])
def test_empty_distribution_is_not_perfect_similarity(tmp_path, metric, source, target):
    gap = FeatureDomainGap(tmp_path)
    with pytest.raises(ValueError, match="empty|nonempty|samples"):
        getattr(gap, metric)(source, target)


@pytest.mark.parametrize("metric", ["mmd", "wasserstein", "mean_gap", "compute"])
@pytest.mark.parametrize("bad", [np.array([[1., np.nan]]), np.array([[np.inf, 2.]])])
def test_nonfinite_distribution_is_rejected(tmp_path, metric, bad):
    with pytest.raises(ValueError, match="finite"):
        getattr(FeatureDomainGap(tmp_path), metric)(bad, np.array([[1., 2.]]))


@pytest.mark.parametrize("metric", ["mmd", "wasserstein", "mean_gap", "compute"])
def test_feature_dimensions_must_match(tmp_path, metric):
    with pytest.raises(ValueError, match="feature dimension"):
        getattr(FeatureDomainGap(tmp_path), metric)([[1., 2.]], [[1., 2., 3.]])


@pytest.mark.parametrize("bad_gamma", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_kernel_bandwidth_is_rejected(tmp_path, bad_gamma):
    with pytest.raises(ValueError, match="gamma"):
        FeatureDomainGap(tmp_path, mmd_gamma=bad_gamma).mmd([1.], [1.])


def test_measured_identical_distributions_yield_zero_gap(tmp_path):
    x = [[1., 2.], [3., 4.]]
    result = FeatureDomainGap(tmp_path).compute(x, x)
    assert result == {"mmd": 0.0, "wasserstein": 0.0, "mean_gap": 0.0}


def test_measured_nonidentical_distributions_are_positive(tmp_path):
    result = FeatureDomainGap(tmp_path).compute([[0.], [1.]], [[2.], [3.]])
    assert all(value > 0 for value in result.values())
