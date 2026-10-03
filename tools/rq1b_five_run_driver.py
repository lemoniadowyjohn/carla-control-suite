#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ1B driver: five isolated cold runs of the full downstream pipeline.

Each run is a separate OS process with:
  - its own BASE_OUTPUT_DIR (reports/rq1b_runs/run_NN)
  - its own UP_RUN_TAG (fixed per-run for determinism)
  - no shared cache: PYTHONPYCACHEPREFIX and TMPDIR are per-run
  - all generation inputs pinned to the governed campaign sources
    (no network access, no Overpass download, no mtime/glob selection)

Emits one receipt per run (rq1_run_receipt/v1) plus a five-run matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EXPECTED_XODR_SHA = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"

PINNED_OSM = "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
PINNED_BUILDINGS = (
    "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_child_env(run_dir: Path, run_idx: int) -> Dict[str, str]:
    """Per-run isolated environment. No shared cache between runs."""
    env = dict(os.environ)

    # Per-run scratch dirs (cold runs: no shared cache)
    cache_root = run_dir / "cache"
    tmp_root = run_dir / "tmp"
    pycache_root = run_dir / "pycache"
    for d in (cache_root, tmp_root, pycache_root):
        d.mkdir(parents=True, exist_ok=True)

    env["PYTHONPYCACHEPREFIX"] = str(pycache_root)
    env["TMP"] = str(tmp_root)
    env["TEMP"] = str(tmp_root)

    # No network: the governed OSM/buildings inputs are pinned on disk.
    env["UP_OSM_FILE"] = str(REPO / PINNED_OSM)
    env["UP_PINNED_BUILDINGS_SOURCE"] = str(REPO / PINNED_BUILDINGS)
    env["UP_DISABLE_OSM_DOWNLOAD"] = "1"
    env["UP_OFFLINE_ONLY"] = "1"

    # Deterministic output naming (no wall-clock in the output path).
    env["UP_RUN_TAG"] = f"rq1b_run{run_idx:02d}"

    # CARLA-dependent stages are out of scope for RQ1B (offline determinism).
    env["UP_CARLA_SAFE_MODE"] = "1"

    return env


def run_one(run_idx: int, out_base: Path) -> Dict[str, Any]:
    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        raise RuntimeError(f"pinned map verification failed: {pinned}")
    if pinned["sha256_actual"] != EXPECTED_XODR_SHA:
        raise RuntimeError(
            f"pinned XODR sha mismatch: {pinned['sha256_actual']} != {EXPECTED_XODR_SHA}"
        )

    run_dir = out_base / f"run_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = build_child_env(run_dir, run_idx)

    # Pass out_base (not run_dir): the child appends run_NN itself, so the
    # receipt lands directly in run_dir where the glob below looks for it.
    cmd = [sys.executable, str(REPO / "tools" / "rq1b_full_pipeline.py"), str(run_idx), str(out_base)]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=7200,
        )
        dur = time.time() - t0
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        dur = time.time() - t0
        timed_out = True
        proc = None
        timeout_exc = exc
    if timed_out:
        (run_dir / "child_stdout.log").write_text("", encoding="utf-8")
        (run_dir / "child_stderr.log").write_text(
            f"TIMEOUT after {dur:.0f}s (limit 7200s): {timeout_exc}", encoding="utf-8"
        )
    else:
        assert proc is not None
        (run_dir / "child_stdout.log").write_text(proc.stdout or "", encoding="utf-8")
        (run_dir / "child_stderr.log").write_text(proc.stderr or "", encoding="utf-8")

    receipts = sorted(run_dir.glob("rq1b_run_*_receipt.json"))
    receipt: Dict[str, Any] = {
        "schema": "rq1b_run_receipt/v1",
        "run_index": run_idx,
        "run_id": f"rq1b_run{run_idx:02d}",
        "input_xodr_sha256": EXPECTED_XODR_SHA,
        "input_xodr_path": pinned["resolved_path"],
        "command": " ".join(cmd),
        "return_code": -1 if timed_out else proc.returncode,
        "timed_out": timed_out,
        "timeout_limit_s": 7200,
        "duration_s": round(dur, 1),
        "isolated": True,
        "shared_cache": False,
        "receipt_found": bool(receipts),
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if receipts:
        receipt["child_receipt"] = json.loads(receipts[0].read_text(encoding="utf-8"))
        receipt["child_receipt_path"] = str(receipts[0])
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description="RQ1B five-run cold determinism driver")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--output-base", type=Path, default=Path("reports/rq1b_runs"))
    args = ap.parse_args()

    out_base = args.output_base
    out_base.mkdir(parents=True, exist_ok=True)

    receipts: List[Dict[str, Any]] = []
    for i in range(args.runs):
        print(f"=== RQ1B run {i:02d} ===", flush=True)
        receipts.append(run_one(i, out_base))
        print(
            f"    rc={receipts[-1]['return_code']} dur={receipts[-1]['duration_s']}s "
            f"receipt={receipts[-1]['receipt_found']}",
            flush=True,
        )

    matrix = {
        "schema": "rq1b_five_run_matrix/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_xodr_sha256": EXPECTED_XODR_SHA,
        "runs_requested": args.runs,
        "runs_completed": len(receipts),
        "all_returncode_zero": all(r["return_code"] == 0 for r in receipts),
        "all_receipts_present": all(r["receipt_found"] for r in receipts),
        "any_timed_out": any(r.get("timed_out") for r in receipts),
        "receipts": receipts,
    }
    (out_base / "RQ1B_FIVE_RUN_MATRIX.json").write_text(
        json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in matrix.items() if k != "receipts"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())