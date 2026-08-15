#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Perception gap feature proxy (lightweight, no torch required).

Goal:
- Provide a deterministic, dependency-light feature vector for images, suitable for
  quick domain-gap proxies (e.g., CORAL or mean matching on feature vectors).

This is intentionally NOT a learned embedding. It's a "cheap and cheerful" proxy.

Features:
- Per-channel mean + std (6)
- Per-channel histogram with 16 bins (48)
- Gradient magnitude histogram with 16 bins (16)
Total: 70 dims
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore

BINS_RGB = 16
BINS_GRAD = 16

def _to_rgb_array(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        img = np.stack([img, img, img], axis=-1)
    if img.ndim != 3 or img.shape[2] < 3:
        raise ValueError(f"Expected HxWx3 image; got {img.shape}")
    img = img[:, :, :3]
    if img.dtype != np.float32:
        img = img.astype(np.float32)
    # Normalize to 0..1 if likely 0..255
    if img.max() > 1.5:
        img = img / 255.0
    return np.clip(img, 0.0, 1.0)

def _grad_mag(gray: np.ndarray) -> np.ndarray:
    # Simple finite differences (no scipy)
    gx = np.zeros_like(gray, dtype=np.float32)
    gy = np.zeros_like(gray, dtype=np.float32)
    gx[:, 1:-1] = 0.5 * (gray[:, 2:] - gray[:, :-2])
    gy[1:-1, :] = 0.5 * (gray[2:, :] - gray[:-2, :])
    return np.sqrt(gx * gx + gy * gy)

def extract_feature_proxy(img: np.ndarray) -> np.ndarray:
    """
    img: numpy array (HxW, HxWxC) uint8/float
    returns: (70,) float32 feature vector
    """
    rgb = _to_rgb_array(img)
    means = rgb.reshape(-1, 3).mean(axis=0)
    stds = rgb.reshape(-1, 3).std(axis=0)

    # RGB histograms
    hists = []
    for c in range(3):
        hist, _ = np.histogram(rgb[:, :, c], bins=BINS_RGB, range=(0.0, 1.0), density=True)
        hists.append(hist.astype(np.float32))
    rgb_hist = np.concatenate(hists, axis=0)

    # Gradient histogram
    gray = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.float32)
    g = _grad_mag(gray)
    # Normalize grad to 0..1-ish for histogram stability
    g = np.clip(g / (g.max() + 1e-6), 0.0, 1.0)
    gh, _ = np.histogram(g, bins=BINS_GRAD, range=(0.0, 1.0), density=True)
    grad_hist = gh.astype(np.float32)

    feat = np.concatenate([means, stds, rgb_hist, grad_hist], axis=0).astype(np.float32)
    return feat

def extract_feature_proxy_from_path(path: str) -> np.ndarray:
    p = Path(path)
    if Image is None:
        raise RuntimeError("Pillow (PIL) is required to load images from path, but is not installed.")
    im = Image.open(p).convert("RGB")
    arr = np.array(im)
    return extract_feature_proxy(arr)
