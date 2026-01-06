#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/augmentation/realism_augmentor.py

Canonical RealismAugmentor for the pipeline.

Compatibility:
- Provides: AugmentationConfig, RealismAugmentor
- Methods expected across your codebase:
    - apply_random(img)  (main API)
    - apply_all(img)     (BACKWARD-COMPAT alias of apply_random)
    - apply_n(img, n)
    - __call__(img)      (alias of apply_random)
- Optional: apply_full(img) applies all ops once (debug / deterministic stack)
- OpenCV optional (motion blur falls back to numpy convolution)
- No global RNG seeding (HPC / multiprocessing safe)
"""

from __future__ import annotations

import importlib
import random
from dataclasses import dataclass
from typing import Optional, Tuple, Callable

import numpy as np

# OpenCV is nice-to-have; don’t hard-crash on HPC nodes
try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore
    _HAS_CV2 = False


@dataclass
class AugmentationConfig:
    # Probabilities
    prob_noise: float = 0.6
    prob_motion_blur: float = 0.4
    prob_brightness: float = 0.7
    prob_color_shift: float = 0.5

    # Determinism (IMPORTANT: do NOT seed global RNGs)
    seed: Optional[int] = None

    # Parameter ranges (explicit for thesis reporting)
    noise_sigma_range: Tuple[float, float] = (5.0, 25.0)
    motion_blur_ksizes: Tuple[int, ...] = (3, 5, 7)
    contrast_alpha_range: Tuple[float, float] = (0.7, 1.4)
    brightness_beta_range: Tuple[int, int] = (-40, 40)
    color_shift_range: Tuple[int, int] = (-20, 20)

    # Optional hook for legacy realism pipelines:
    # "some.module:func" where func(img: np.ndarray) -> np.ndarray
    external_hook: Optional[str] = None


class RealismAugmentor:
    """
    Photometric augmentation module (noise/blur/brightness/color shift).

    Input:  HxWxC uint8 (preferred) or float in [0,255].
            C can be 1, 3, or 4 (alpha preserved if present).
    Output: uint8 HxWxC
    """

    def __init__(self, config: AugmentationConfig | None = None):
        self.config = config or AugmentationConfig()

        # Local RNGs (deterministic per instance if seed set)
        self._py_rng = random.Random(self.config.seed)
        self._np_rng = np.random.default_rng(self.config.seed)

        self._hook_fn: Optional[Callable[[np.ndarray], np.ndarray]] = self._resolve_hook(
            self.config.external_hook
        )

    # -----------------------
    # Public API (stable)
    # -----------------------

    def __call__(self, img: np.ndarray) -> np.ndarray:
        return self.apply_random(img)

    def apply_random(self, img: np.ndarray) -> np.ndarray:
        """
        Apply a random combination of augmentations (probability-driven).
        """
        base, alpha = self._split_alpha(img)
        out = base.copy()

        if self._py_rng.random() < self.config.prob_noise:
            out = self.add_gaussian_noise(out)

        if self._py_rng.random() < self.config.prob_motion_blur:
            out = self.add_motion_blur(out)

        if self._py_rng.random() < self.config.prob_brightness:
            out = self.adjust_brightness_contrast(out)

        if self._py_rng.random() < self.config.prob_color_shift:
            out = self.color_shift(out)

        if self._hook_fn is not None:
            try:
                out2 = self._hook_fn(out)
                if isinstance(out2, np.ndarray):
                    out = out2
            except Exception:
                # Never let an external hook crash the pipeline
                pass

        return self._merge_alpha(out, alpha)

    def apply_all(self, img: np.ndarray) -> np.ndarray:
        """
        BACKWARDS-COMPATIBILITY:
        Older code calls apply_all() meaning "apply augmentation".

        We intentionally make this an alias of apply_random().
        If you want 'apply every augmentation once', use apply_full().
        """
        return self.apply_random(img)

    def apply_full(self, img: np.ndarray) -> np.ndarray:
        """
        Apply *all* augmentations once (non-probabilistic).
        Useful for debugging and for showing examples in the thesis.
        """
        base, alpha = self._split_alpha(img)
        out = base.copy()

        out = self.add_gaussian_noise(out)
        out = self.add_motion_blur(out)
        out = self.adjust_brightness_contrast(out)
        out = self.color_shift(out)

        if self._hook_fn is not None:
            try:
                out2 = self._hook_fn(out)
                if isinstance(out2, np.ndarray):
                    out = out2
            except Exception:
                pass

        return self._merge_alpha(out, alpha)

    def apply_n(self, img: np.ndarray, n: int) -> Tuple[np.ndarray, ...]:
        """
        Generate n independently augmented variants.
        """
        n = int(n)
        if n <= 0:
            return tuple()
        return tuple(self.apply_random(img) for _ in range(n))

    # -----------------------
    # Basic ops
    # -----------------------

    def add_gaussian_noise(self, img: np.ndarray) -> np.ndarray:
        img = self._ensure_uint8(img)
        sigma = self._py_rng.uniform(*self.config.noise_sigma_range)

        h, w = img.shape[:2]
        # noise per pixel, broadcast across channels (keeps colors coherent)
        noise = self._np_rng.normal(0.0, sigma, size=(h, w, 1)).astype(np.float32)
        out = img.astype(np.float32) + noise
        return self._ensure_uint8(out)

    def add_motion_blur(self, img: np.ndarray) -> np.ndarray:
        img = self._ensure_uint8(img)

        ksize = self._py_rng.choice(self.config.motion_blur_ksizes)
        if ksize <= 1:
            return img

        kernel = np.zeros((ksize, ksize), dtype=np.float32)
        if self._py_rng.random() < 0.5:
            kernel[ksize // 2, :] = 1.0  # horizontal
        else:
            kernel[:, ksize // 2] = 1.0  # vertical
        kernel /= float(kernel.sum())

        if _HAS_CV2:
            return self._ensure_uint8(cv2.filter2D(img, -1, kernel))  # type: ignore

        # Fallback (no cv2): minimal numpy convolution (slow but small kernels)
        return self._ensure_uint8(self._conv2d_numpy(img, kernel))

    def adjust_brightness_contrast(self, img: np.ndarray) -> np.ndarray:
        img = self._ensure_uint8(img)
        alpha = self._py_rng.uniform(*self.config.contrast_alpha_range)  # contrast
        beta = self._py_rng.randint(*self.config.brightness_beta_range)  # brightness
        out = img.astype(np.float32) * float(alpha) + float(beta)
        return self._ensure_uint8(out)

    def color_shift(self, img: np.ndarray) -> np.ndarray:
        img = self._ensure_uint8(img)

        # grayscale or no color channels -> no-op
        if img.ndim != 3 or img.shape[2] < 3:
            return img

        lo, hi = self.config.color_shift_range
        shift = self._np_rng.integers(lo, hi + 1, size=(1, 1, 3), dtype=np.int32).astype(np.float32)

        out = img.astype(np.float32)
        out[:, :, :3] = out[:, :, :3] + shift
        return self._ensure_uint8(out)

    # -----------------------
    # Internals
    # -----------------------

    @staticmethod
    def _ensure_uint8(img: np.ndarray) -> np.ndarray:
        if img.dtype != np.uint8:
            img = np.clip(img, 0, 255).astype(np.uint8)
        else:
            img = np.clip(img, 0, 255)
        return img

    @staticmethod
    def _split_alpha(img: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        If img is RGBA/BGRA, return (rgb, alpha). Otherwise (img, None).
        """
        if img.ndim == 3 and img.shape[2] == 4:
            base = img[:, :, :3]
            alpha = img[:, :, 3:4]
            return base, alpha
        return img, None

    @staticmethod
    def _merge_alpha(base: np.ndarray, alpha: Optional[np.ndarray]) -> np.ndarray:
        if alpha is None:
            return base
        base = RealismAugmentor._ensure_uint8(base)
        alpha = RealismAugmentor._ensure_uint8(alpha)
        # ensure alpha has correct shape (HxWx1)
        if alpha.ndim == 2:
            alpha = alpha[:, :, None]
        return np.concatenate([base, alpha], axis=2)

    @staticmethod
    def _resolve_hook(hook: Optional[str]) -> Optional[Callable[[np.ndarray], np.ndarray]]:
        """
        Resolve "module.submodule:function" into a callable.
        """
        if not hook or ":" not in hook:
            return None
        mod_name, fn_name = hook.split(":", 1)
        try:
            mod = importlib.import_module(mod_name)
            fn = getattr(mod, fn_name, None)
            return fn if callable(fn) else None
        except Exception:
            return None

    @staticmethod
    def _conv2d_numpy(img: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """
        Minimal conv2d fallback for motion blur if OpenCV is missing.
        Applies the kernel to each channel independently.
        """
        img_f = img.astype(np.float32)
        kh, kw = kernel.shape
        pad_h, pad_w = kh // 2, kw // 2

        # handle grayscale
        if img_f.ndim == 2:
            img_f = img_f[:, :, None]

        padded = np.pad(img_f, ((pad_h, pad_h), (pad_w, pad_w), (0, 0)), mode="edge")
        out = np.zeros_like(img_f, dtype=np.float32)

        # naive but fine for small ksizes
        for y in range(out.shape[0]):
            for x in range(out.shape[1]):
                patch = padded[y:y + kh, x:x + kw, :]
                out[y, x, :] = (patch * kernel[:, :, None]).sum(axis=(0, 1))

        if out.shape[2] == 1:
            out = out[:, :, 0]
        return out


__all__ = ["AugmentationConfig", "RealismAugmentor"]
