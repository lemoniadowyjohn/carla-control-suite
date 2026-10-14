"""Per-frame semantic-label quality checks for the segmentation dataset.

R8 trains a segmentation model on synthetic (auto-map) frames and evaluates the
sim-to-real gap. A frame whose label mask is all-background (or dominated by one
class, e.g. empty sky/road) contributes nothing to training and can bias the
gap measurement. These helpers quantify per-frame label quality so degenerate
frames can be flagged/filtered. Pure numpy; no CARLA dependency (offline-safe).
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_MAX_CLASS_ID

# The valid CARLA label space partitions into exactly three disjoint pixel
# categories (NEW-276):
#   unlabeled : id 0    -- CARLA's Unlabeled/None background
#   learnable : id 1..CARLA_SEMANTIC_MAX_CLASS_ID -- named semantic classes
#   any       : id 255  -- carla.CityObjectLabel.Any sentinel (unclassified;
#               training loss ignores it via ignore_index=255, see
#               min_train_segmentation.py / train_launcher.py)
_UNLABELED_CLASS_ID = 0
_LEARNABLE_MIN_CLASS_ID = 1
_LEARNABLE_MAX_CLASS_ID = CARLA_SEMANTIC_MAX_CLASS_ID


def label_stats(raw_ids: Any) -> Dict[str, float]:
    """Return quality stats for a single-channel class-id mask (uint8 class ids).

    - ``n_classes``: number of distinct class ids present.
    - ``nonbackground_fraction``: fraction of pixels with a non-zero class id
      (class 0 is CARLA's Unlabeled/None background). Note this legacy figure
      lumps the Any(255) sentinel in with real labels; use
      ``learnable_fraction`` for the share of pixels that actually carry
      learnable semantic content.
    - ``dominant_class_fraction``: fraction of pixels held by the single most
      common class id.

    The three-way split (NEW-276), exhaustive over the valid label space
    ``[0, CARLA_SEMANTIC_MAX_CLASS_ID]`` and the Any sentinel, and summing to
    1.0 for any valid mask:

    - ``unlabeled_fraction``: fraction of pixels with id 0 (background).
    - ``learnable_fraction``: fraction of pixels with a named semantic class id
      in ``[1, CARLA_SEMANTIC_MAX_CLASS_ID]`` -- the pixels a training loss
      actually learns from.
    - ``any_fraction``: fraction of pixels with the Any(255) sentinel, which
      the training loss ignores entirely.

    Ids outside the valid label space contribute to none of the three split
    buckets (this function reports, it does not validate; see
    ``carla_classes.assert_label_ids_in_range`` for validation).
    """
    a = np.asarray(raw_ids)
    total = int(a.size)
    if total == 0:
        return {
            "n_classes": 0,
            "nonbackground_fraction": 0.0,
            "dominant_class_fraction": 1.0,
            "unlabeled_fraction": 0.0,
            "learnable_fraction": 0.0,
            "any_fraction": 0.0,
        }
    _, counts = np.unique(a, return_counts=True)
    nonbg = int(np.count_nonzero(a))
    unlabeled = int(np.count_nonzero(a == _UNLABELED_CLASS_ID))
    any_sentinel = int(np.count_nonzero(a == CARLA_SEMANTIC_ANY_CLASS_ID))
    learnable = int(
        np.count_nonzero((a >= _LEARNABLE_MIN_CLASS_ID) & (a <= _LEARNABLE_MAX_CLASS_ID))
    )
    return {
        "n_classes": int(counts.size),
        "nonbackground_fraction": nonbg / total,
        "dominant_class_fraction": float(counts.max()) / total,
        "unlabeled_fraction": unlabeled / total,
        "learnable_fraction": learnable / total,
        "any_fraction": any_sentinel / total,
    }


def is_degenerate_label(
    raw_ids: Any,
    *,
    min_classes: int = 2,
    max_dominant_fraction: float = 0.98,
    min_learnable_fraction: float = 0.0,
) -> bool:
    """True if the label frame is unlearnable: fewer than ``min_classes`` distinct
    classes, a single class covers more than ``max_dominant_fraction`` of pixels,
    or the learnable fraction (see ``label_stats``) is below
    ``min_learnable_fraction``.

    ``min_learnable_fraction`` catches frames padded with Any(255) sentinel or
    background pixels that pass the class-count/dominance checks while carrying
    almost no learnable label content. The default 0.0 preserves the original
    behavior for callers that do not opt in.
    """
    s = label_stats(raw_ids)
    if s["learnable_fraction"] < min_learnable_fraction:
        return True
    return s["n_classes"] < min_classes or s["dominant_class_fraction"] > max_dominant_fraction
