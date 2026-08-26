from __future__ import annotations

import numpy as np
import pytest

from ultimate_pipeline.perception.carla_classes import (
    CARLA_SEMANTIC_NUM_CLASSES,
    assert_label_ids_in_range,
)


def test_num_classes_is_29_not_256():
    assert CARLA_SEMANTIC_NUM_CLASSES == 29


def test_constant_matches_live_carla_enum_when_available():
    carla = pytest.importorskip("carla")
    labels = carla.CityObjectLabel
    tags = [
        int(getattr(labels, name))
        for name in dir(labels)
        if not name.startswith("_") and isinstance(getattr(labels, name), labels)
    ]
    normal_max = max(tag for tag in tags if tag < 100)  # Exclude Any=255 query filter.
    assert CARLA_SEMANTIC_NUM_CLASSES == normal_max + 1


def test_assert_label_ids_in_range_accepts_valid_tags():
    assert_label_ids_in_range(np.array([0, 7, 28], dtype=np.uint8))


def test_assert_label_ids_in_range_rejects_out_of_range():
    with pytest.raises(ValueError):
        assert_label_ids_in_range(np.array([0, 29], dtype=np.int64))
    with pytest.raises(ValueError):
        # 200 is neither a named class (0-28) nor carla.CityObjectLabel.Any (255) --
        # genuine corruption. 255 is now accepted: it's CARLA's real Any sentinel,
        # not corruption (verified against the installed carla package; see C27).
        assert_label_ids_in_range(np.array([200], dtype=np.uint8))


def test_assert_label_ids_in_range_accepts_any_sentinel():
    # carla.CityObjectLabel.Any == 255 (verified against the installed carla package)
    # -- a real, common value in captures (unclassified/miscellaneous pixels), not
    # corruption. Must not be rejected.
    assert_label_ids_in_range(np.array([0, 7, 255], dtype=np.uint8))


def test_assert_label_ids_in_range_empty_is_ok():
    assert_label_ids_in_range(np.array([], dtype=np.uint8))
