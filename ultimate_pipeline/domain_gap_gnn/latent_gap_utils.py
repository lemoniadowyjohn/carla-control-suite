#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities for comparing latent embeddings.

This module exists to avoid circular imports between CLI runners and metric helpers.

The primary entrypoint used across the codebase is :func:`combine_latent_gaps`.
"""

from __future__ import annotations

from typing import Dict

import torch


def _as_2d(z: torch.Tensor) -> torch.Tensor:
    """Ensure z is [B, D]."""
    if not isinstance(z, torch.Tensor):
        raise TypeError(f"Expected torch.Tensor, got {type(z)!r}")
    if z.ndim == 1:
        return z.unsqueeze(0)
    if z.ndim == 2:
        return z
    # Some models may return extra dims (e.g. [B, 1, D]); flatten all but batch.
    return z.view(z.shape[0], -1)


def combine_latent_gaps(z_manual: torch.Tensor, z_auto: torch.Tensor) -> Dict[str, float]:
    """Compute a small, stable set of distances between two latent vectors.

    Args:
        z_manual: manual-town embedding tensor (shape [B, D] or [D])
        z_auto: auto-map embedding tensor (shape compatible with z_manual)

    Returns:
        Dict of scalar metrics (python floats).
    """
    zm = _as_2d(z_manual).detach()
    za = _as_2d(z_auto).detach()

    if zm.shape != za.shape:
        raise ValueError(f"Latent shapes differ: manual={tuple(zm.shape)} auto={tuple(za.shape)}")

    # Compute per-item metrics then average over batch for stability.
    diff = zm - za
    l1 = diff.abs().mean(dim=1)
    l2 = diff.pow(2).sum(dim=1).sqrt()
    mse = diff.pow(2).mean(dim=1)

    # Cosine distance = 1 - cosine similarity.
    eps = 1e-8
    zm_n = zm / (zm.norm(dim=1, keepdim=True) + eps)
    za_n = za / (za.norm(dim=1, keepdim=True) + eps)
    cos_sim = (zm_n * za_n).sum(dim=1).clamp(-1.0, 1.0)
    cos_dist = 1.0 - cos_sim

    return {
        "l1_mean": float(l1.mean().cpu().item()),
        "l2": float(l2.mean().cpu().item()),
        "mse": float(mse.mean().cpu().item()),
        "cosine_distance": float(cos_dist.mean().cpu().item()),
        "cosine_similarity": float(cos_sim.mean().cpu().item()),
    }
