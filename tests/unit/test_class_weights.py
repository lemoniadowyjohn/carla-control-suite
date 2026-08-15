from __future__ import annotations

import sys

import numpy as np
import pytest
from PIL import Image

from ultimate_pipeline.perception import min_train_segmentation
from ultimate_pipeline.perception.class_weights import (
    compute_class_weights,
    scan_label_class_counts,
)


def test_median_frequency_weights_raise_rare_class_over_common_class():
    weights = compute_class_weights([1000, 100, 0], num_classes=3, scheme="median_frequency")

    assert weights.shape == (3,)
    assert float(weights[1]) > float(weights[0])
    assert float(weights[2]) == 0.0


def test_uniform_distribution_gets_equal_present_weights():
    weights = compute_class_weights([10, 10, 10], num_classes=3, scheme="median_frequency")

    assert weights.tolist() == pytest.approx([1.0, 1.0, 1.0])


def test_inverse_frequency_weights_raise_rare_class_over_common_class():
    weights = compute_class_weights([1000, 100], num_classes=2, scheme="inverse_frequency")

    assert float(weights[1]) > float(weights[0])


def test_scan_label_class_counts_counts_raw_id_pngs(tmp_path):
    label = tmp_path / "000001.png"
    Image.fromarray(np.array([[0, 1, 1], [2, 2, 2]], dtype=np.uint8), mode="L").save(label)

    counts = scan_label_class_counts([label], num_classes=4)

    assert counts.tolist() == [1, 2, 3, 0]


def test_scan_label_class_counts_rejects_out_of_range_ids(tmp_path):
    label = tmp_path / "bad.png"
    Image.fromarray(np.array([[0, 255]], dtype=np.uint8), mode="L").save(label)

    with pytest.raises(ValueError, match="0, 28"):
        scan_label_class_counts([label], num_classes=29)


def test_min_train_class_weights_default_on_and_opt_out(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["train", "--dataset", "dataset_root"])
    assert min_train_segmentation.parse_args().no_class_weights is False

    monkeypatch.setattr(
        sys,
        "argv",
        ["train", "--dataset", "dataset_root", "--no-class-weights"],
    )
    assert min_train_segmentation.parse_args().no_class_weights is True
