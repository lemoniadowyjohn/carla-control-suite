# tests/test_augmentation_realism.py
from __future__ import annotations

import numpy as np

from ultimate_pipeline.augmentation.realism_augmentor import (
    RealismAugmentor,
    AugmentationConfig,
)


def _dummy_image() -> np.ndarray:
    # simple gradient test image
    h, w = 256, 256
    x = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
    img = np.stack([x, x, x], axis=-1)
    return img


def test_augmentation_preserves_shape_and_dtype():
    img = _dummy_image()
    aug = RealismAugmentor(AugmentationConfig(seed=123))

    out = aug.apply_random(img)

    assert out.shape == img.shape
    assert out.dtype == np.uint8


def test_augmentation_changes_image_most_of_the_time():
    img = _dummy_image()
    aug = RealismAugmentor(AugmentationConfig(seed=123))

    outs = [aug.apply_random(img) for _ in range(5)]
    diffs = [np.mean(np.abs(o.astype(float) - img.astype(float))) for o in outs]

    # At least one augmentation should be noticeably different
    assert any(d > 1.0 for d in diffs)


def test_apply_n_returns_correct_number():
    img = _dummy_image()
    aug = RealismAugmentor(AugmentationConfig(seed=123))

    variants = aug.apply_n(img, 4)
    assert len(variants) == 4
    for out in variants:
        assert out.shape == img.shape
        assert out.dtype == np.uint8
