#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 Trial Run - Single full-pipeline trial against the pinned map-of-record.

Emits the full rq1_run_receipt/v1 schema required by rq1_five_run_matrix.py:
  xodr_sha256, normalized_xodr_sha256, structural_signature, feature_counts,
  topology_counts, output_path, tileset_digest, map_acceptance_digest,
  final_receipt_digest

Usage:
    python tools/rq1_trial_run.py <run_index> [<output_base_dir>] [--mode=A|B]

Mode A: pinned OSM -> Osm2Odr repeated N>=5 times (RQ1A)
Mode B: one pinned XODR -> full downstream pipeline repeated N>=5 times (RQ1B)
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


def _extract_structural_signature(reports: Dict[str, Any]) -> Optional[str]:
    """Extract or compute the structural signature from pipeline reports."""
    # The structural signature is typically in the topology certification
    comp = reports.get("component_reachability_literal")
    if isinstance(comp, dict):
        return _sha256_dict(comp)
    # Fallback: hash the component reachability recovery report
    comp = reports.get("component_reachability")
    if isinstance(comp, dict):
        return _sha256_dict(comp)
    return None


def _extract_feature_counts(reports: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract feature counts from map acceptance metrics."""
    # These come from map_acceptance metrics
    return None  # Will be filled from map_acceptance


def _extract_topology_counts(reports: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Extract topology counts from pipeline reports."""
    return None  # Will be filled from map_acceptance


def _extract_tileset_digest(reports: Dict[str, Any]) -> Optional[str]:
    """Extract tileset digest from tile QA reports."""
    # The tileset digest is computed during tile QA
    tile_qa = reports.get("tile_qa")
    if isinstance(tile_qa, dict):
        return tile_qa.get("tileset_digest_sha256")
    return None


def run_single_trial(
    run_idx: int,
    out_base: Path,
    mode: str = "B",
) -> Dict[str, Any]:
    """Execute a legacy RQ1B trial; this is not the governed v2 campaign."""
    if mode != "B":
        raise ValueError(
            "Mode A is not implemented by rq1_trial_run.py; "
            "use the dedicated RQ1A OSM-to-OpenDRIVE runner"
        )
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        raise RuntimeError(f"Map verification failed: {pinned}")
    in_xodr = pinned["resolved_path"]
    input_sha = pinned["sha256_actual"]

    out_base = Path(out_base) / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = in_xodr
    s.BASE_OUTPUT_DIR = str(out_base)
    s.QA_AUTOVIS = False

    t0 = time.time()
    try:
        pipeline = MainPipeline(settings=s)
        out_dir = pipeline.run()
        status = "ok"
        error = ""
        reports = getattr(pipeline, "stage_reports", {})
        map_acceptance = getattr(pipeline, "map_acceptance", {})
    except Exception as e:
        out_dir = str(out_base)
        status = f"FAILED: {type(e).__name__}: {e}"
        error = str(e)[:500]
        reports = {}
        map_acceptance = {}
    dur = time.time() - t0

    # Build full receipt from map_acceptance and reports
    final_xodr = map_acceptance.get("final_xodr_path") if map_acceptance else None
    final_xodr_sha = _digest_file(final_xodr) if final_xodr else None

    # No canonical normalization occurs in this legacy v1 runner.
    # Never present the raw-byte digest as an independently computed
    # normalized digest.
    normalized_xodr_sha = None

    # Structural signature
    structural_sig = _extract_structural_signature(reports)

    # Feature counts from map_acceptance metrics
    feature_counts = None
    topology_counts = None
    tileset_digest = None
    map_acceptance_digest = None
    final_receipt_digest = None

    if map_acceptance:
        feature_counts = {
            k: v for k, v in map_acceptance.get("metrics", {}).items()
            if isinstance(v, int) and "count" in k.lower()
        }
        topology_counts = {
            k: v for k, v in map_acceptance.get("metrics", {}).items()
            if isinstance(v, int) and ("component" in k.lower() or "lane" in k.lower() or "junction" in k.lower() or "road" in k.lower())
        }
        # Tileset digest
        tileset_digest = map_acceptance.get("linked_artifact_sha256", {}).get("tileset_digest")
        # Map acceptance digest
        map_acceptance_digest = map_acceptance.get("payload_sha256")
        # Final receipt digest
        final_receipt_digest = map_acceptance.get("acceptance_artifact_sha256")

    # A payload checksum is not a structural signature; keep absence explicit.
    if status == "ok" and not all((
        final_xodr_sha,
        map_acceptance_digest,
        final_receipt_digest,
        structural_sig,
    )):
        status = "FAILED_INCOMPLETE_RECEIPT"
        error = "missing final artifact or independent structural/evidence identity"

    receipt = {
        "schema": "rq1_run_receipt/v1",
        "run": run_idx,
        "mode": mode,
        "status": status,
        "error": error,
        "duration_s": round(dur, 1),
        "input_xodr": in_xodr,
        "input_sha256": input_sha,
        "out_dir": str(out_dir),
        "xodr_sha256": final_xodr_sha,
        "normalized_xodr_sha256": normalized_xodr_sha,
        "structural_signature": structural_sig,
        "feature_counts": feature_counts,
        "topology_counts": topology_counts,
        "output_path": str(out_dir),
        "tileset_digest": tileset_digest,
        "map_acceptance_digest": map_acceptance_digest,
        "final_receipt_digest": final_receipt_digest,
        "map_acceptance": map_acceptance,
    }

    # Write receipt
    receipt_path = Path(out_base) / f"rq1_run_{run_idx:02d}_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return receipt


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/rq1_trial_run.py <run_index> [<output_base_dir>] [--mode=A|B]", file=sys.stderr)
        return 2

    run_idx = int(sys.argv[1])
    base = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path("reports/rq1_trial_runs")
    mode = "B"
    if "--mode=A" in sys.argv:
        mode = "A"
    elif "--mode=B" in sys.argv:
        mode = "B"
    if mode == "A":
        print("RQ1A is not implemented by this runner; use tools/rq1a_osm2odr.py", file=sys.stderr)
        return 2

    receipt = run_single_trial(run_idx, base, mode)
    print(json.dumps({"status": receipt["status"], "run": receipt["run"], "mode": receipt["mode"]}, indent=2))
    return 0 if receipt["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())