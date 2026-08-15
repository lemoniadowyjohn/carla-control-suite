"""Compatibility API for CARLA semantic class policy."""
from __future__ import annotations

from typing import Any

import numpy as np

from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_MAX_CLASS_ID,
    CARLA_SEMANTIC_NUM_CLASSES,
)


def assert_label_ids_in_range(raw_ids: Any) -> None:
    arr = np.asarray(raw_ids)
    if arr.size == 0:
        return
    min_id = int(arr.min())
    max_id = int(arr.max())
    if min_id < 0 or max_id > CARLA_SEMANTIC_MAX_CLASS_ID:
        raise ValueError(
            f"CARLA semantic label ids must be in [0, {CARLA_SEMANTIC_MAX_CLASS_ID}], "
            f"got range [{min_id}, {max_id}]"
        )
