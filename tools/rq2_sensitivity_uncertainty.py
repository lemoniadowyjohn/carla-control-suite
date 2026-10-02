#!/usr/bin/env python3
"""Batch-10 RQ2 lane driver: sensitivity + spatial uncertainty (lane-local only)."""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(__file__, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ultimate_pipeline.domain_gap.rq2_sensitivity_analysis import run_sensitivity
from ultimate_pipeline.domain_gap.rq2_uncertainty_report import build_uncertainty_report

RUN_ID = os.environ.get("RQ2_RUN_ID", "20261002_batch10")
OUT_DIR = os.path.join(ROOT, "reports", "parallel_wave", "rq2", RUN_ID)

AUTO = os.path.join(
    ROOT,
    "campaigns",
    "ingolstadt_cooked_perception_v1",
    "candidate",
    "ingolstadt_perception_map_of_record_20260916_232831.xodr",
)
MANUAL = os.path.join(
    ROOT,
    "campaigns",
    "ingolstadt_cooked_perception_v1",
    "source",
    "manual",
    "Grid0828.xodr",
)


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "RQ2_RESULTS.json"), encoding="utf-8") as f:
        cand = json.load(f)

    print("[rq2] uncertainty (spatial blocks)...", flush=True)
    t0 = time.time()
    unc = build_uncertainty_report(AUTO, MANUAL, grid=(2, 2))
    unc["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT_DIR, "RQ2_UNCERTAINTY.json"), "w", encoding="utf-8") as f:
        json.dump(unc, f, indent=2)
    print("[rq2] uncertainty done.", flush=True)

    print("[rq2] sensitivity variants...", flush=True)
    t0 = time.time()
    sens = run_sensitivity(AUTO, MANUAL, primary=cand["manual_hull"]["primary"])
    sens["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT_DIR, "RQ2_SENSITIVITY.json"), "w", encoding="utf-8") as f:
        json.dump(sens, f, indent=2)
    print("[rq2] sensitivity done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
