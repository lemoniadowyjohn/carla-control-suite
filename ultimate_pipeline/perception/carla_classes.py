"""Compatibility API for CARLA semantic class policy."""
from __future__ import annotations

from typing import Any

import numpy as np

from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_MAX_CLASS_ID,
    CARLA_SEMANTIC_NUM_CLASSES,
)

# carla.CityObjectLabel.Any == 255 (verified against the installed carla package):
# CARLA's own sentinel for unclassified/miscellaneous pixels, a normal and common
# value in real semantic-segmentation captures -- distinct from, and not part of,
# the contiguous 0..CARLA_SEMANTIC_MAX_CLASS_ID named-class range.
CARLA_SEMANTIC_ANY_CLASS_ID = 255


def assert_label_ids_in_range(raw_ids: Any) -> None:
    arr = np.asarray(raw_ids)
    if arr.size == 0:
        return
    min_id = int(arr.min())
    max_id = int(arr.max())
    bad = arr[(arr < 0) | ((arr > CARLA_SEMANTIC_MAX_CLASS_ID) & (arr != CARLA_SEMANTIC_ANY_CLASS_ID))]
    if bad.size > 0:
        raise ValueError(
            f"CARLA semantic label ids must be in [0, {CARLA_SEMANTIC_MAX_CLASS_ID}] "
            f"or the Any sentinel ({CARLA_SEMANTIC_ANY_CLASS_ID}), "
            f"got range [{min_id}, {max_id}]"
        )
