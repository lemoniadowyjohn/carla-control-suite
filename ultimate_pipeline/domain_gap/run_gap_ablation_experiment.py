#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import subprocess
import copy
from typing import Dict, Any

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap


# ============================================================
# Paths
# ============================================================

PIPELINE_ENTRY = os.path.join(
    os.path.dirname(__file__),
    "..",
    "main_pipeline.py",
)

OUT_ROOT = os.path.join(
    SETTINGS.BASE_OUTPUT_DIR,
    "ablations",
)


# ============================================================
# Helpers
# ============================================================

def _snapshot_settings(keys: Dict[str, bool]) -> Dict[str, Any]:
    """Capture current SETTINGS values for given keys."""
    snap = {}
    for k in keys:
        if not hasattr(SETTINGS, k):
            raise KeyError(f"Unknown setting in ablation: {k}")
        snap[k] = getattr(SETTINGS, k)
    return snap


def _apply_ablation(cfg: Dict[str, bool]) -> None:
    """Apply ablation config to SETTINGS."""
    for k, v in cfg.items():
        setattr(SETTINGS, k, v)


def _restore_settings(snapshot: Dict[str, Any]) -> None:
    """Restore SETTINGS from snapshot."""
    for k, v in snapshot.items():
        setattr(SETTINGS, k, v)


def _run_pipeline(seed: int) -> str:
    env = os.environ.copy()
    env["PIPELINE_SEED_OVERRIDE"] = str(seed)

    subprocess.run(
        [os.sys.executable, PIPELINE_ENTRY],
        check=True,
        env=env,
    )
    return SETTINGS.latest_output_dir()


def _find_auto_xodr(out_dir: str) -> str:
    # os.listdir() order is arbitrary/OS-dependent, and a real "08_final"
    # stage writes several variants (plain, semantic copy,
    # laneSectionFixed repair, semantic re-copy of the repair) --
    # `next(...)` over an unordered listing could pick any of them
    # non-deterministically. mtime-newest matches the already-established
    # convention elsewhere (artifact_locator.py, export_thesis_tables.py)
    # and correctly picks the post-repair map, which the repair step
    # exists specifically to make CARLA-safe.
    candidates = sorted(
        (f for f in os.listdir(out_dir) if f.startswith("08_final") and f.endswith(".xodr")),
        key=lambda f: os.path.getmtime(os.path.join(out_dir, f)),
        reverse=True,
    )
    return os.path.join(out_dir, candidates[0])


# ============================================================
# Main ablation runner
# ============================================================

def run_domain_gap_ablation(seed: int = 0) -> None:
    manual_xodr = SETTINGS.MANUAL_MAP_XODR
    if not manual_xodr:
        raise RuntimeError("MANUAL_MAP_XODR not set")

    os.makedirs(OUT_ROOT, exist_ok=True)

    print("\n🧪 DOMAIN GAP ABLATION STUDY")
    print(f"Seed: {seed}")
    print(f"Manual map: {manual_xodr}")

    for name, cfg in SETTINGS.DOMAIN_GAP_ABLATIONS.items():
        print(f"\n▶ Ablation: {name}")

        ablation_dir = os.path.join(OUT_ROOT, name)
        os.makedirs(ablation_dir, exist_ok=True)

        # --- snapshot + apply ---
        snapshot = _snapshot_settings(cfg)
        _apply_ablation(cfg)

        try:
            out_dir = _run_pipeline(seed)
            auto_xodr = _find_auto_xodr(out_dir)

            gap_out = os.path.join(out_dir, "domain_gap")

            gap = run_full_domain_gap(
                manual_xodr=manual_xodr,
                auto_xodr=auto_xodr,
                manual_tiles=SETTINGS.MANUAL_TILES_DIR or "",
                auto_tiles=os.path.join(out_dir, "tiles"),
                output_dir=gap_out,
            )

            # --- enrich metadata ---
            gap["experiment_type"] = "ablation"
            gap["ablation_name"] = name
            gap["ablation_config"] = cfg
            gap["seed"] = seed
            gap["pipeline_out_dir"] = out_dir

            out_path = os.path.join(ablation_dir, "result.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(gap, f, indent=2)

            print(f"✅ Ablation '{name}' finished → {out_path}")

        finally:
            # --- ALWAYS restore ---
            _restore_settings(snapshot)


if __name__ == "__main__":
    run_domain_gap_ablation(seed=0)
