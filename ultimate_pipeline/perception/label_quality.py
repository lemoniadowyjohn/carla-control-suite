"""Per-frame semantic-label quality checks for the segmentation dataset.

R8 trains a segmentation model on synthetic (auto-map) frames and evaluates the
sim→real gap. A frame whose label mask is all-background (or dominated by one
class, e.g. empty sky/road) contributes nothing to training and can bias the
gap measurement. These helpers quantify per-frame label quality so degenerate
frames can be flagged/filtered. Pure numpy — no CARLA dependency (offline-safe).
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np


def label_stats(raw_ids: Any) -> Dict[str, float]:
    """Return quality stats for a single-channel class-id mask (uint8 class ids).

    - ``n_classes``: number of distinct class ids present.
    - ``nonbackground_fraction``: fraction of pixels with a non-zero class id
      (class 0 is CARLA's Unlabeled/None background).
    - ``dominant_class_fraction``: fraction of pixels held by the single most
      common class id.
    """
    a = np.asarray(raw_ids)
    total = int(a.size)
    if total == 0:
        return {"n_classes": 0, "nonbackground_fraction": 0.0, "dominant_class_fraction": 1.0}
    _, counts = np.unique(a, return_counts=True)
    nonbg = int(np.count_nonzero(a))
    return {
        "n_classes": int(counts.size),
        "nonbackground_fraction": nonbg / total,
        "dominant_class_fraction": float(counts.max()) / total,
    }


def is_degenerate_label(
    raw_ids: Any,
    *,
    min_classes: int = 2,
    max_dominant_fraction: float = 0.98,
) -> bool:
    """True if the label frame is unlearnable: fewer than ``min_classes`` distinct
    classes, or a single class covers more than ``max_dominant_fraction`` of pixels."""
    s = label_stats(raw_ids)
    return s["n_classes"] < min_classes or s["dominant_class_fraction"] > max_dominant_fraction
