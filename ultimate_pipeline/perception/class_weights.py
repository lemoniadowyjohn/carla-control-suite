from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image
import torch

from ultimate_pipeline.perception.carla_classes import assert_label_ids_in_range
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES


def compute_class_weights(
    label_id_counts: Sequence[int] | np.ndarray,
    *,
    num_classes: int = CARLA_SEMANTIC_NUM_CLASSES,
    scheme: str = "median_frequency",
) -> torch.Tensor:
    """Compute deterministic per-class CE weights from label-id pixel counts."""
    counts = np.asarray(label_id_counts, dtype=np.float64).reshape(-1)
    if counts.size > int(num_classes):
        raise ValueError(
            f"label_id_counts has {counts.size} entries, exceeds num_classes={num_classes}"
        )
    if np.any(counts < 0):
        raise ValueError("label_id_counts must be non-negative")

    padded = np.zeros(int(num_classes), dtype=np.float64)
    padded[: counts.size] = counts
    present = padded > 0.0
    if not np.any(present):
        return torch.zeros(int(num_classes), dtype=torch.float32)

    total = float(padded[present].sum())
    freq = np.zeros_like(padded)
    freq[present] = padded[present] / total

    weights = np.zeros_like(padded)
    if scheme == "median_frequency":
        median_freq = float(np.median(freq[present]))
        weights[present] = median_freq / freq[present]
    elif scheme == "inverse_frequency":
        inv = 1.0 / freq[present]
        weights[present] = inv / float(np.mean(inv))
    else:
        raise ValueError(
            "Unsupported class-weight scheme "
            f"{scheme!r}; expected 'median_frequency' or 'inverse_frequency'"
        )

    return torch.as_tensor(weights, dtype=torch.float32)


def scan_label_class_counts(
    label_paths: Iterable[str | Path],
    *,
    num_classes: int = CARLA_SEMANTIC_NUM_CLASSES,
) -> np.ndarray:
    """Accumulate class-id pixel counts from raw semantic PNG masks."""
    counts = np.zeros(int(num_classes), dtype=np.int64)
    for label_path in label_paths:
        arr = np.array(Image.open(label_path).convert("L"), dtype=np.uint8)
        assert_label_ids_in_range(arr)
        counts += np.bincount(arr.reshape(-1), minlength=int(num_classes))[: int(num_classes)]
    return counts


def scan_dataset_class_counts(
    dataset_root: str | Path,
    *,
    camera: str,
    limit: int | None = None,
    num_classes: int = CARLA_SEMANTIC_NUM_CLASSES,
) -> np.ndarray:
    """Scan ``semseg_raw/<camera>`` under a thesis segmentation dataset."""
    label_dir = Path(dataset_root) / "semseg_raw" / str(camera)
    paths = sorted(label_dir.glob("*.png"))
    if limit is not None and int(limit) > 0:
        paths = paths[: int(limit)]
    return scan_label_class_counts(paths, num_classes=num_classes)
