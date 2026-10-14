#!/usr/bin/env python3
"""RQ1B: Post-Generation Pipeline Determinism Experiment.

Tests whether the post-generation pipeline (given a fixed XODR input)
produces byte-for-byte identical outputs across multiple runs.

This isolates the post-generation pipeline stages (topology repair, enrichment,
elevation, lane generation, tiling, etc.) from the OSM→XODR stage, allowing
determinism testing of just the post-generation pipeline independent of
OSM→XODR conversion variability.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.main_pipeline import MainPipeline


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_dict(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _compute_tileset_digest(output_dir: Path) -> str:
    tiles = sorted(output_dir.rglob("*.fbx")) + sorted(output_dir.rglob("*.xodr"))
    if not tiles:
        return ""
    h = hashlib.sha256()
    for t in tiles:
        h.update(t.read_bytes())
    return h.hexdigest()


def _compute_map_acceptance_digest(output_dir: Path) -> str:
    acceptance_files = sorted(output_dir.rglob("*acceptance*.json"))
    if not acceptance_files:
        return ""
    h = hashlib.sha256()
    for f in acceptance_files:
        h.update(f.read_bytes())
    return h.hexdigest()


def _compute_settings_hash(settings: Any) -> str:
    settings_dict = {}
    for attr in dir(settings):
        if not attr.startswith("_") and not callable(getattr(settings, attr, None)):
            try:
                val = getattr(settings, attr)
                if isinstance(val, (str, int, float, bool, type(None))):
                    settings_dict[attr] = val
            except Exception:
                pass
    return hashlib.sha256(
        json.dumps(settings_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="RQ1B: Post-Generation Pipeline Determinism Test")
    parser.add_argument("run_index", type=int, help="Run index (0-4 for 5-run matrix)")
    parser.add_argument("--fixed-xodr", type=Path, required=True, help="Fixed XODR input path")
    parser.add_argument("--output-base", type=Path, default=Path("reports/rq1b_runs"),
                        help="Base output directory")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs (default 5)")
    args = parser.parse_args()

    run_idx = args.run_index
    base = args.output_base
    base.mkdir(parents=True, exist_ok=True)

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = str(args.fixed_xodr)
    s.BASE_OUTPUT_DIR = str(base / f"run_{args.run_index:02d}")
    s.QA_AUTOVIS = False
    s.QA_VERBOSE = False
    s.ENABLE_LOCAL_PERCEPTION = False
    s.ENABLE_HPC_PERCEPTION = False
    s.ENABLE_HPC_EXPORT = False
    s.ENABLE_LOCAL_PERCEPTION = False

    run_dir = base / f"run_{args.run_index:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    s2 = copy.copy(SETTINGS)
    s2.INPUT_XODR = str(args.fixed_xodr)
    s2.BASE_OUTPUT_DIR = str(base / f"run_{args.run_index:02d}")
    s2.QA_AUTOVIS = False
    s2.QA_VERBOSE = False
    s2.ENABLE_LOCAL_PERCEPTION = False
    s2.ENABLE_HPC_PERCEPTION = False
    s2.ENABLE_HPC_EXPORT = False

    # Disable CARLA-dependent stages for offline determinism
    os.environ["UP_CARLA_ISOLATION"] = "0"
    os.environ["UP_INTERACTIVE"] = "0"

    t0 = time.time()
    status = "ok"
    error = ""
    out_dir = None

    try:
        out_dir = MainPipeline(settings=s2).run()
        status = "ok"
        error = ""
    except Exception as e:
        out_dir = str(run_dir)
        status = f"FAILED: {type(e).__name__}: {e}"
        error = str(e)[:500]

    dur = time.time() - t0

    tileset_digest = ""
    map_acceptance_digest = ""
    settings_hash = ""

    if out_dir:
        tileset_digest = _compute_tileset_digest(Path(out_dir))
        map_acceptance_digest = _compute_map_acceptance_digest(Path(out_dir))

    settings_hash = hashlib.sha256(
        json.dumps({
            k: getattr(SETTINGS, k)
            for k in dir(SETTINGS)
            if k.isupper() and not callable(getattr(SETTINGS, k))
        }, sort_keys=True, default=str).encode()
    ).hexdigest()

    receipt = {
        "schema": "rq1b_run_receipt/v1",
        "run_index": args.run_index,
        "status": "ok" if status == "ok" else "FAILED",
        "error": error,
        "duration_s": round(time.time() - time.time(), 3),
        "fixed_xodr_sha256": _sha256(Path(args.fixed_xodr)),
        "tileset_digest": "",
        "map_acceptance_digest": "",
        "final_receipt_digest": "",
        "per_stage_hashes": {},
        "per_stage_durations": {"total": round(time.time() - t0, 1)},
        "per_stage_status": {"pipeline": "ok" if status == "ok" else "FAILED"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": "local_working_tree",
        "settings_hash": "",
    }

    # Compute all digests
    receipt["fixed_xodr_sha256"] = _sha256(Path(args.fixed_xodr))
    receipt["tileset_digest"] = tileset_digest
    receipt["map_acceptance_digest"] = map_acceptance_digest
    receipt["settings_hash"] = _compute_settings_hash(SETTINGS)

    # Compute final receipt digest
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    receipt["final_receipt_digest"] = hashlib.sha256(receipt_json.encode()).hexdigest()

    receipt["duration_s"] = round(time.time() - t0, 3)
    receipt["status"] = "ok" if status == "ok" else "FAILED"
    receipt["error"] = error
    receipt["duration_s"] = round(dur, 3)
    receipt["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["git_commit"] = "local_working_tree"
    receipt["settings_hash"] = _compute_settings_hash(SETTINGS)
    receipt["schema"] = "rq1b_run_receipt/v1"
    receipt["run_index"] = args.run_index

    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    receipt["final_receipt_digest"] = hashlib.sha256(receipt_json.encode()).hexdigest()

    receipt_path = base / f"run_{args.run_index:02d}" / "rq1b_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "run": args.run_index,
        "status": receipt["status"],
        "tileset_digest": tileset_digest,
        "map_acceptance_digest": map_acceptance_digest,
        "receipt_sha": receipt["final_receipt_digest"],
    }, indent=2))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())