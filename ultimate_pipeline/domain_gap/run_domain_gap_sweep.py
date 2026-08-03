#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import subprocess
import statistics
import sys
from typing import Dict, Any, List

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap


# ============================================================
# CONFIG — single source of truth
# ============================================================

SWEEP_SEEDS = [0, 1, 2, 3, 4]     # thesis-safe: 5–10
SWEEP_TAG = "domain_gap_sweep_v1"

PIPELINE_ENTRY = os.path.join(
    os.path.dirname(__file__),
    "..",
    "main_pipeline.py",
)

OUT_ROOT = os.path.join(
    SETTINGS.BASE_OUTPUT_DIR,
    "sweeps",
    SWEEP_TAG,
)


# ============================================================
# Helpers
# ============================================================

def _run_pipeline_with_seed(seed: int) -> str:
    """
    Runs main_pipeline.py with a deterministic seed override.
    Returns the pipeline output directory.
    """
    env = os.environ.copy()
    env["PIPELINE_SEED_OVERRIDE"] = str(seed)

    subprocess.run(
        [sys.executable, PIPELINE_ENTRY],
        check=True,
        env=env,
    )

    return SETTINGS.latest_output_dir()


def _safe_get(d: Dict[str, Any], path: List[str]) -> float | None:
    """
    Safely extract a nested scalar metric.
    """
    v: Any = d
    for k in path:
        if not isinstance(v, dict):
            return None
        v = v.get(k)
    return float(v) if isinstance(v, (int, float)) else None


def _collect(all_runs: List[Dict[str, Any]], path: List[str]) -> List[float]:
    vals: List[float] = []
    for r in all_runs:
        v = _safe_get(r, path)
        if v is not None:
            vals.append(v)
    return vals


def _summary_stats(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"mean": 0.0, "std": 0.0, "n": 0}

    mean = statistics.mean(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0

    return {
        "mean": mean,
        "std": std,
        "n": len(vals),
    }


# ============================================================
# Main sweep
# ============================================================

def run_domain_gap_sweep() -> None:
    os.makedirs(OUT_ROOT, exist_ok=True)

    manual_xodr = SETTINGS.MANUAL_MAP_XODR
    if not manual_xodr:
        raise RuntimeError("MANUAL_MAP_XODR not set")

    all_runs: List[Dict[str, Any]] = []

    print("\n🚀 DOMAIN GAP SWEEP")
    print(f"Seeds: {SWEEP_SEEDS}")
    print(f"Manual map: {manual_xodr}")

    for seed in SWEEP_SEEDS:
        print(f"\n▶ Pipeline run (seed={seed})")

        out_dir = _run_pipeline_with_seed(seed)

        auto_xodr = next(
            os.path.join(out_dir, f)
            for f in os.listdir(out_dir)
            if f.startswith("08_final") and f.endswith(".xodr")
        )

        gap_out = os.path.join(out_dir, SETTINGS.DOMAIN_GAP_OUT_DIR)

        gap = run_full_domain_gap(
            manual_xodr=manual_xodr,
            auto_xodr=auto_xodr,
            manual_tiles=SETTINGS.MANUAL_TILES_DIR or "",
            auto_tiles=os.path.join(out_dir, "tiles"),
            output_dir=gap_out,
        )

        # --- provenance ---
        gap["seed"] = seed
        gap["pipeline_out_dir"] = out_dir
        gap["pipeline_version"] = getattr(SETTINGS, "PIPELINE_VERSION", None)

        all_runs.append(gap)

    # ========================================================
    # Aggregate MEASURED statistics (no hypotheses here)
    # ========================================================

    metrics = {
        "geometry_rmse": _collect(
            all_runs,
            ["structural_domain_gap", "geometry", "rmse"],
        ),
        "geometry_hausdorff_norm": _collect(
            all_runs,
            ["structural_domain_gap", "geometry", "hausdorff_norm"],
        ),
        "curvature_kl": _collect(
            all_runs,
            ["structural_domain_gap", "curvature", "kl_divergence"],
        ),
        "intersection_delta": _collect(
            all_runs,
            ["structural_domain_gap", "intersections", "delta_norm"],
        ),
    }

    summary = {
        "sweep_tag": SWEEP_TAG,
        "n_runs": len(all_runs),
        "metrics": {
            k: _summary_stats(v)
            for k, v in metrics.items()
        },
        "notes": {
            "interpretation": (
                "All values are empirically measured across independent "
                "deterministic pipeline runs. No target or claimed gaps "
                "are assumed."
            )
        },
    }

    # ========================================================
    # Save results
    # ========================================================

    with open(os.path.join(OUT_ROOT, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(OUT_ROOT, "sweep_all_runs.json"), "w") as f:
        json.dump(all_runs, f, indent=2)

    print("\n✅ DOMAIN GAP SWEEP COMPLETE")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_domain_gap_sweep()
