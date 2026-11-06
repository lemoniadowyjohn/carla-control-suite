#!/usr/bin/env python3
"""Generate a complete RQ1 run receipt (rq1_run_receipt/v1 schema)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.main_pipeline import MainPipeline
from ultimate_pipeline.core.xodr_sanitizer import XODRSanitizer
from ultimate_pipeline.tools.xodr_coordinate_report import _extract_planview_points_stream as extract_road_geometry_start_points


def _git_commit_hash(worktree: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


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
    return _hash_dict(settings_dict)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/rq1_complete_receipt.py <run_index> [<output_base_dir>]", file=sys.stderr)
        return 1

    pinned = verify_pinned_map("auto_map_of_record")
    assert pinned.get("verification_status") == "VERIFIED", pinned
    in_xodr = pinned["resolved_path"]

    run_idx = int(sys.argv[1])
    base = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/rq1_trial_runs")
    out_base = base / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = in_xodr
    s.BASE_OUTPUT_DIR = str(out_base)
    s.QA_AUTOVIS = False

    input_sha256 = pinned["sha256_actual"]
    settings_hash = _compute_settings_hash(SETTINGS)

    t0 = time.time()
    status = "ok"
    error = ""
    out_dir = None

    s2 = copy.copy(SETTINGS)
    s2.INPUT_XODR = in_xodr
    s2.BASE_OUTPUT_DIR = str(out_base)
    s2.QA_AUTOVIS = False

    try:
        out_dir = MainPipeline(settings=s2).run()
        status = "ok"
        error = ""
    except Exception as e:
        out_dir = str(out_base)
        status = f"FAILED: {type(e).__name__}: {e}"
        error = str(e)[:500]

    dur = time.time() - t0
    out_path = Path(out_dir) if out_dir else out_base

    if not normalized_xodr.exists():
        try:
            XODRSanitizer.sanitize_xodr(str(in_xodr), str(out_base / "normalized.xodr"))
        except Exception:
            pass

    normalized_xodr_sha256 = _sha256(normalized_xodr) if normalized_xodr.exists() else ""
    structural_signature = _sha256(Path(in_xodr))  # simplified
    feature_counts = _compute_feature_counts(in_xodr)
    topology_counts = _compute_topology_counts(in_xodr)
    tileset_digest = _compute_tileset_digest(out_path) if out_path.exists() else ""
    map_acceptance_digest = _compute_map_acceptance_digest(out_path) if out_path.exists() else ""
    settings_hash = _compute_settings_hash(SETTINGS)

    receipt = {
        "schema": "rq1_run_receipt/v1",
        "run_index": run_idx,
        "status": "ok" if status == "ok" else "FAILED",
        "error": error,
        "duration_s": round(time.time() - t0, 1),
        "input_xodr": in_xodr,
        "input_sha256": pinned.get("sha256_actual", ""),
        "normalized_xodr_sha256": normalized_xodr_sha256,
        "structural_signature": structural_signature,
        "feature_counts": feature_counts,
        "topology_counts": topology_counts,
        "output_path": str(out_base),
        "tileset_digest": tileset_digest,
        "map_acceptance_digest": map_acceptance_digest,
        "final_receipt_digest": "",
        "per_stage_hashes": {},
        "per_stage_durations": {"total": round(dur, 1)},
        "per_stage_status": {"pipeline": status},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit_hash(WORKTREE),
        "settings_hash": settings_hash,
    }

    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    receipt["final_receipt_digest"] = hashlib.sha256(receipt_json.encode()).hexdigest()

    receipt_path = out_base / "rq1_run_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "run": run_idx,
        "status": receipt["status"],
        "error": error,
        "duration_s": receipt["duration_s"],
        "input_sha256": receipt["input_sha256"],
        "normalized_xodr_sha256": receipt["normalized_xodr_sha256"],
        "structural_signature": receipt["structural_signature"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt["final_receipt_digest"],
    }, indent=1))

    return 0 if status == "ok" else 1
