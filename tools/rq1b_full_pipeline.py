#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1B: Pinned XODR → Full Downstream Pipeline Determinism (N≥5)

Repeats the full downstream pipeline from a pinned XODR through all stages
to final map-of-record and tile QA. Each run must produce identical outputs
(structural_signature, feature_counts, topology_counts, tileset_digest,
map_acceptance_digest, final_receipt_digest).

Usage:
    python tools/rq1b_full_pipeline.py <run_index> [<output_base_dir>]

Schema: rq1_run_receipt/v1
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.main_pipeline import MainPipeline
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance
from ultimate_pipeline.quality.map_acceptance import safe_sha256_file


def _sha256_dict(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _digest_file(path: Optional[str]) -> Optional[str]:
    if path and os.path.exists(path):
        return safe_sha256_file(path)
    return None


def _extract_structural_signature(map_acceptance: Dict[str, Any]) -> Optional[str]:
    """Extract structural signature from map acceptance payload."""
    # The structural signature is the payload SHA256 of the map acceptance
    return map_acceptance.get("payload_sha256")


def _extract_feature_counts(map_acceptance: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract feature counts from map acceptance metrics."""
    if not map_acceptance:
        return None
    metrics = map_acceptance.get("metrics", {})
    return {
        k: v for k, v in metrics.items()
        if isinstance(v, int) and any(kw in k.lower() for kw in ["count", "buildings", "signals", "traffic_light", "lane", "junction", "road", "building"])
    }


def _extract_topology_counts(map_acceptance: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract topology counts from map acceptance metrics."""
    if not map_acceptance:
        return None
    metrics = map_acceptance.get("metrics", {})
    return {
        k: v for k, v in metrics.items()
        if isinstance(v, int) and any(kw in k.lower() for kw in ["component", "lane", "junction", "road", "lane_width", "elevation", "seam", "smoothness", "physics", "origin", "junction", "lane_width", "lane_geometry", "elevation_smooth", "physics_feas"])
    }


def _extract_tileset_digest(map_acceptance: Dict[str, Any]) -> Optional[str]:
    """Extract tileset digest from map acceptance linked artifacts."""
    if not map_acceptance:
        return None
    return map_acceptance.get("linked_artifact_sha256", {}).get("tileset_digest")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/rq1b_full_pipeline.py <run_index> [<output_base_dir>]", file=sys.stderr)
        sys.exit(1)

    run_idx = int(sys.argv[1])
    base = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/rq1b_runs")
    out_base = base / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    # Verify pinned map
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        raise RuntimeError(f"Map verification failed: {pinned}")
    in_xodr = pinned["resolved_path"]
    input_sha = pinned["sha256_actual"]

    out_dir = out_base / "rq1b_full"
    out_dir.mkdir(parents=True, exist_ok=True)

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = in_xodr
    s.BASE_OUTPUT_DIR = str(out_dir)
    s.QA_AUTOVIS = False

    import time
    t0 = time.time()
    try:
        pipeline = MainPipeline(settings=s)
        out_dir_str = pipeline.run()
        status = "ok"
        error = ""
        map_acceptance = getattr(pipeline, "map_acceptance", {})
    except Exception as e:
        out_dir_str = str(out_dir)
        status = f"FAILED: {type(e).__name__}: {e}"
        error = str(e)[:500]
        map_acceptance = {}
    dur = time.time() - t0

    # Extract receipt fields from map_acceptance
    final_xodr = map_acceptance.get("final_xodr_path") if map_acceptance else None
    final_xodr_sha = _digest_file(final_xodr) if final_xodr else None
    normalized_xodr_sha = final_xodr_sha  # No normalization step currently
    structural_signature = _extract_structural_signature(map_acceptance) if map_acceptance else None
    feature_counts = _extract_feature_counts(map_acceptance)
    topology_counts = _extract_topology_counts(map_acceptance)
    tileset_digest = _extract_tileset_digest(map_acceptance)
    map_acceptance_digest = map_acceptance.get("payload_sha256") if map_acceptance else None
    final_receipt_digest = map_acceptance.get("acceptance_artifact_sha256") if map_acceptance else None

    receipt = {
        "schema": "rq1_run_receipt/v1",
        "run": 0,
        "mode": "B",
        "status": status,
        "error": error if 'error' in locals() else "",
        "duration_s": round(dur, 1),
        "input_xodr": in_xodr,
        "input_sha256": input_sha,
        "out_dir": str(out_dir_str) if 'out_dir_str' in locals() else str(out_dir),
        "xodr_sha256": final_xodr_sha,
        "normalized_xodr_sha256": normalized_xodr_sha,
        "structural_signature": structural_signature,
        "feature_counts": feature_counts,
        "topology_counts": topology_counts,
        "output_path": str(out_dir),
        "tileset_digest": tileset_digest,
        "map_acceptance_digest": map_acceptance_digest,
        "final_receipt_digest": final_receipt_digest,
        "map_acceptance": map_acceptance,
    }

    receipt_path = Path(out_base) / f"rq1b_run_{0:02d}_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "run": receipt["run"], "mode": receipt["mode"]}, indent=2))


if __name__ == "__main__":
    main()