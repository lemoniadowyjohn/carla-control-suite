#!/usr/bin/env python3
"""
Task 4: Permutation test on N>=30 GNN/MLP embeddings.

Tests whether the observed cross-cosine separation between auto and manual
embedding centroids exceeds chance (null: label permutation).

Method:
  1. Load embeddings from _embeddings_n30.npz
  2. Compute observed cross-cosine between auto centroid and manual centroid
  3. Run K=1000 permutations: shuffle auto/manual labels, recompute cross-cosine
  4. p-value = fraction of permutation cross-cosines <= observed (one-sided:
     testing if observed is MORE NEGATIVE / more separated than chance)
  5. Save permutation_test_n30.json

NOTE: Since NT-Xent is self-supervised (not class-discriminative), the
permutation test uses centroid cross-cosine as the test statistic.
A p-value < 0.05 means the observed label separation exceeds chance at alpha=0.05.
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RESULT_DIR = Path("C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/submission/results/gnn_v1_full")
EMBEDDINGS_PATH = RESULT_DIR / "_embeddings_n30.npz"
COLLAPSE_PATH = RESULT_DIR / "collapse_check_n30.json"
OUT_PATH = RESULT_DIR / "permutation_test_n30.json"

K_PERMUTATIONS = 1000
SEED = 42


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cross_mean_cosine_centroids(Z: np.ndarray, mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Cosine similarity between centroid of Z[mask_a] and centroid of Z[mask_b]."""
    Za = Z[mask_a]
    Zb = Z[mask_b]
    if len(Za) == 0 or len(Zb) == 0:
        return 0.0
    centroid_a = Za.mean(axis=0)
    centroid_b = Zb.mean(axis=0)
    return cosine_similarity(centroid_a, centroid_b)


def cross_mean_cosine_all_pairs(Z: np.ndarray, mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Mean cosine similarity across all (a, b) pairs."""
    Za = Z[mask_a]
    Zb = Z[mask_b]
    if len(Za) == 0 or len(Zb) == 0:
        return 0.0
    an = Za / (np.linalg.norm(Za, axis=1, keepdims=True) + 1e-12)
    bn = Zb / (np.linalg.norm(Zb, axis=1, keepdims=True) + 1e-12)
    return float((an @ bn.T).mean())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    set_seed(SEED)

    print("=== TASK 4: Permutation Test (N>=30) ===")
    print(f"Embeddings: {EMBEDDINGS_PATH}")
    print(f"K = {K_PERMUTATIONS} permutations")

    if not EMBEDDINGS_PATH.exists():
        print(f"ERROR: Embeddings file not found: {EMBEDDINGS_PATH}", file=sys.stderr)
        sys.exit(1)

    # Load embeddings
    data = np.load(str(EMBEDDINGS_PATH), allow_pickle=True)
    Z_all = data["Z_all"]  # [N, latent_dim]
    labels = data["labels"]  # [N] array of strings
    ids = data["ids"]  # [N] array of strings

    n_total = len(Z_all)
    auto_mask = labels == "auto"
    manual_mask = labels == "manual"
    n_auto = int(auto_mask.sum())
    n_manual = int(manual_mask.sum())

    print(f"Total samples: {n_total} (auto={n_auto}, manual={n_manual})")

    # Observed test statistics
    observed_centroid = cross_mean_cosine_centroids(Z_all, auto_mask, manual_mask)
    observed_all_pairs = cross_mean_cosine_all_pairs(Z_all, auto_mask, manual_mask)

    print(f"Observed cross-cosine (centroids):  {observed_centroid:.6f}")
    print(f"Observed cross-cosine (all pairs):  {observed_all_pairs:.6f}")

    # Permutation test
    # Null hypothesis: observed centroid cross-cosine is not different from chance
    # Test: H1: observed cross-cosine is lower (more negative/separated) than null
    # p-value = P(null_stat <= observed) under label permutation

    indices = np.arange(n_total)
    null_centroids: List[float] = []
    null_all_pairs: List[float] = []

    print(f"\nRunning {K_PERMUTATIONS} permutations...")
    for k in range(K_PERMUTATIONS):
        perm = np.random.permutation(indices)
        perm_auto_mask = np.zeros(n_total, dtype=bool)
        perm_auto_mask[perm[:n_auto]] = True
        perm_manual_mask = np.zeros(n_total, dtype=bool)
        perm_manual_mask[perm[n_auto:n_auto + n_manual]] = True

        null_c = cross_mean_cosine_centroids(Z_all, perm_auto_mask, perm_manual_mask)
        null_p = cross_mean_cosine_all_pairs(Z_all, perm_auto_mask, perm_manual_mask)
        null_centroids.append(null_c)
        null_all_pairs.append(null_p)

        if (k + 1) % 200 == 0:
            print(f"  [{k+1}/{K_PERMUTATIONS}] null centroid mean so far: {np.mean(null_centroids):.4f}")

    null_centroids_arr = np.array(null_centroids)
    null_all_pairs_arr = np.array(null_all_pairs)

    # p-value: fraction of null statistics <= observed
    # (for cross-cosine: lower = more separated; we test if observed is unusually low)
    p_value_centroid = float(np.mean(null_centroids_arr <= observed_centroid))
    p_value_all_pairs = float(np.mean(null_all_pairs_arr <= observed_all_pairs))

    null_centroid_mean = float(null_centroids_arr.mean())
    null_centroid_std = float(null_centroids_arr.std())
    null_all_pairs_mean = float(null_all_pairs_arr.mean())
    null_all_pairs_std = float(null_all_pairs_arr.std())

    # Percentile of observed in null
    observed_percentile = float(np.mean(null_centroids_arr <= observed_centroid) * 100)

    print(f"\n=== Permutation Test Results ===")
    print(f"Observed centroid cross-cosine:  {observed_centroid:.6f}")
    print(f"Null distribution mean:          {null_centroid_mean:.6f}")
    print(f"Null distribution std:           {null_centroid_std:.6f}")
    print(f"p-value (centroid):              {p_value_centroid:.4f}")
    print(f"p-value (all pairs):             {p_value_all_pairs:.4f}")

    alpha = 0.05
    significant_centroid = p_value_centroid < alpha
    significant_all_pairs = p_value_all_pairs < alpha

    if significant_centroid:
        verdict = "SIGNIFICANT_SEPARATION"
        rq4_upgrade = "OBSERVATIONAL_TO_SUPPORTED"
        verdict_text = (
            f"The latent-space separation between auto and manual tile embeddings "
            f"is statistically significant (p={p_value_centroid:.4f} < {alpha}). "
            f"This upgrades RQ4 from purely observational to statistically supported."
        )
    else:
        verdict = "NOT_SIGNIFICANT"
        rq4_upgrade = "REMAINS_OBSERVATIONAL"
        verdict_text = (
            f"The observed separation (cross-cosine={observed_centroid:.4f}) is not "
            f"statistically significant at alpha={alpha} (p={p_value_centroid:.4f}). "
            f"The result remains observational; a larger or more balanced sample "
            f"is recommended for definitive statistical confirmation."
        )

    print(f"\nVerdict: {verdict}")
    print(f"RQ4 upgrade: {rq4_upgrade}")
    print(f"{verdict_text}")

    payload = {
        "schema_version": "n30_v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": "label_permutation_centroid_cross_cosine",
        "k_permutations": int(K_PERMUTATIONS),
        "seed": int(SEED),
        "alpha": float(alpha),
        "n_total": int(n_total),
        "n_auto": int(n_auto),
        "n_manual": int(n_manual),
        "observed_cross_cosine_centroids": float(observed_centroid),
        "observed_cross_cosine_all_pairs": float(observed_all_pairs),
        "null_distribution": {
            "centroid_mean": float(null_centroid_mean),
            "centroid_std": float(null_centroid_std),
            "centroid_min": float(null_centroids_arr.min()),
            "centroid_max": float(null_centroids_arr.max()),
            "centroid_p5": float(np.percentile(null_centroids_arr, 5)),
            "centroid_p95": float(np.percentile(null_centroids_arr, 95)),
            "all_pairs_mean": float(null_all_pairs_mean),
            "all_pairs_std": float(null_all_pairs_std),
        },
        "p_value_centroid": float(p_value_centroid),
        "p_value_all_pairs": float(p_value_all_pairs),
        "significant_at_alpha_05_centroid": bool(significant_centroid),
        "significant_at_alpha_05_all_pairs": bool(significant_all_pairs),
        "observed_percentile_in_null": float(observed_percentile),
        "verdict": verdict,
        "rq4_upgrade": rq4_upgrade,
        "verdict_text": verdict_text,
        "note": (
            "This permutation test operates on structural-feature MLP embeddings (N=45 tiles, "
            "9 features). The primary GNN result (lane-graph GCN, N=72, cross-cosine=-0.160) "
            "remains the thesis-grade evidence. This test provides additional statistical "
            "grounding. The primary encoder is NT-Xent self-supervised, so permutation "
            "significance depends on whether the learned representation happens to separate "
            "auto/manual tiles as a consequence of structural distribution differences."
        ),
    }

    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nPermutation test results saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
