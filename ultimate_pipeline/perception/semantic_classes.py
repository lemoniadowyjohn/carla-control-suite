"""CARLA semantic-segmentation class policy.

CARLA semantic masks are stored as numeric class IDs, not compact ordinal class
indices. The segmentation head therefore needs at least ``max_id + 1`` outputs.
Using 256 outputs is safe for uint8 masks but adds mostly-dead logits that dilute
unlabeled real-domain pooled-logit metrics.
"""
from __future__ import annotations

CARLA_SEMANTIC_MAX_CLASS_ID = 28
CARLA_SEMANTIC_NUM_CLASSES = CARLA_SEMANTIC_MAX_CLASS_ID + 1


def validate_num_classes(
    num_classes: int,
    *,
    max_required_class_id: int = CARLA_SEMANTIC_MAX_CLASS_ID,
) -> int:
    resolved = int(num_classes)
    min_required = int(max_required_class_id) + 1
    if resolved < min_required:
        raise ValueError(
            f"num_classes={resolved} is too small for CARLA semantic id "
            f"{max_required_class_id}; use at least {min_required}"
        )
    return resolved
