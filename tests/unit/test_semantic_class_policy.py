import sys

import pytest
import torch

from ultimate_pipeline.perception import eval_real_unlabeled, eval_sim_labeled, min_train_segmentation
from ultimate_pipeline.perception.carla_classes import assert_label_ids_in_range


def test_carla_semantic_policy_right_sizes_default_head():
    from ultimate_pipeline.perception.semantic_classes import (
        CARLA_SEMANTIC_MAX_CLASS_ID,
        CARLA_SEMANTIC_NUM_CLASSES,
        validate_num_classes,
    )

    assert CARLA_SEMANTIC_MAX_CLASS_ID == 28
    assert CARLA_SEMANTIC_NUM_CLASSES == 29
    validate_num_classes(CARLA_SEMANTIC_NUM_CLASSES)
    with pytest.raises(ValueError, match="too small"):
        validate_num_classes(CARLA_SEMANTIC_MAX_CLASS_ID)


def test_train_and_eval_cli_defaults_use_carla_semantic_class_count(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["train", "--dataset", "dataset_root"],
    )
    assert min_train_segmentation.parse_args().num_classes == 29

    monkeypatch.setattr(
        sys,
        "argv",
        ["eval-sim", "--model", "model.pt", "--dataset", "dataset_root"],
    )
    assert eval_sim_labeled.parse_args().num_classes == 29

    monkeypatch.setattr(
        sys,
        "argv",
        ["eval-real", "--model", "model.pt", "--real-dir", "real_images"],
    )
    assert eval_real_unlabeled.parse_args().num_classes == 29


def test_pooled_logits_dimension_matches_right_sized_head():
    logits = torch.zeros((2, 29, 4, 3), dtype=torch.float32)

    pooled = eval_real_unlabeled._pooled_logits(logits)

    assert tuple(pooled.shape) == (2, 29)


def test_label_ids_fail_closed_outside_carla_segmentation_range():
    assert_label_ids_in_range(torch.tensor([0, 7, 28]))
    # 200 is genuine corruption -- neither a named class (0-28) nor carla.CityObjectLabel.Any
    # (255, now accepted; verified against the installed carla package, see C27).
    with pytest.raises(ValueError, match="0, 28"):
        assert_label_ids_in_range(torch.tensor([0, 200]))
    assert_label_ids_in_range(torch.tensor([0, 255]))  # Any sentinel must not raise


def test_settings_train_num_classes_env_override(monkeypatch):
    from ultimate_pipeline.config import settings as settings_module

    assert settings_module._env_float("UP_TEST_FLOAT_MISSING", 1.25) == pytest.approx(1.25)
    monkeypatch.setenv("UP_TEST_FLOAT_VALUE", "2.5")
    monkeypatch.setenv("UP_TEST_INT_VALUE", "31")

    assert settings_module._env_float("UP_TEST_FLOAT_VALUE", 1.25) == pytest.approx(2.5)
    assert settings_module._env_int("UP_TEST_INT_VALUE", 29) == 31
