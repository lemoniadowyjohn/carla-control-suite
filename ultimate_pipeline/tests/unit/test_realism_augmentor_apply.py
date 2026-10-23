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


def test_apply_honours_instance_config():
    """O5/G04b: the instance's own probability settings must be honoured.

    An instance with every probability at 0.0 must make apply() an identity
    transform; a fresh default config silently discarded by the old
    implementation would apply noise instead.
    """
    from ultimate_pipeline.augmentation.realism_augmentor import AugmentationConfig

    img = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    zero_cfg = AugmentationConfig(
        prob_noise=0.0, prob_motion_blur=0.0, prob_brightness=0.0, prob_color_shift=0.0
    )
    out = RealismAugmentor(zero_cfg).apply(img, 42)
    assert np.array_equal(out, img), "apply() discarded the instance's prob_*=0.0 config"


def test_apply_different_seed_changes_output():
    """O5/G04b: different seeds on the default config produce different output."""
    img = np.random.default_rng(2).integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
    a = RealismAugmentor().apply(img, 7)
    b = RealismAugmentor().apply(img, 8)
    assert not np.array_equal(a, b), "different seeds must not collide"


def test_apply_rejects_none_image():
    """O5/G04b: img=None must fail fast with a clear TypeError."""
    for raised in (False,):
        try:
            RealismAugmentor().apply(None, 1)
        except TypeError:
            raised = True
        except AttributeError as exc:
            raise AssertionError(f"apply(None) raised AttributeError, not TypeError: {exc}")
        assert raised, "apply(None, 1) did not raise TypeError"
