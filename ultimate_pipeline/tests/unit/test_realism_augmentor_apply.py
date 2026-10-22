#!/usr/bin/env python3
"""Focused test for the restored RealismAugmentor.apply(img, seed) convenience
method (B01 repair, Step 4): it must return an ndarray with the same shape and
dtype as its input.
"""

import numpy as np

from ultimate_pipeline.augmentation.realism_augmentor import RealismAugmentor


def test_apply_returns_ndarray_same_shape_and_dtype():
    img = np.random.default_rng(0).integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
    out = RealismAugmentor().apply(img, 123)

    assert isinstance(out, np.ndarray), f"expected ndarray, got {type(out)!r}"
    assert out.shape == img.shape, f"shape changed: {out.shape} != {img.shape}"
    assert out.dtype == img.dtype, f"dtype changed: {out.dtype} != {img.dtype}"


def test_apply_is_deterministic_for_fixed_seed():
    img = np.random.default_rng(1).integers(0, 256, size=(6, 6, 3), dtype=np.uint8)
    a = RealismAugmentor().apply(img, 42)
    b = RealismAugmentor().apply(img, 42)

    assert np.array_equal(a, b), "same seed must produce identical output"
