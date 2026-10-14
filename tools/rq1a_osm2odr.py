#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1A: Pinned OSM → Osm2Odr Determinism (N≥5)

Repeats the OSM → Osm2Odr stage against the pinned map-of-record source OSM.
Each run must produce identical XODR output (structural_signature, xodr_sha256, etc.).

Usage:
    python tools/rq1a_osm2odr.py <run_index> [<output_base_dir>]

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


def _sha256_dict(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _digest_file(path: Optional[str]) -> Optional[str]:
    if path and os.path.exists(path):
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    return None


def _run_osm2odr_only(settings) -> Dict[str, Any]:
    """Run only the Osm2Odr stage (stage 01) and return the XODR path and metadata."""
    from ultimate_pipeline.pipeline_stages import stage_01_osm2odr
    from ultimate_pipeline.config.settings import SETTINGS as SETTINGS_CLS
    
    # Create a settings copy for Osm2Odr only
    s = copy.copy(SETTINGS)
    s.INPUT_XODR = None  # Will be generated from OSM
    # The Osm2Odr stage reads from SETTINGS.INPUT_OSM
    # We need to set the OSM source from the pinned map registry
    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
    pinned = verify_pinned_map("auto_map_of_record")
    # Get the source OSM path from the pinned map's provenance
    # This is a simplification; actual Osm2Odr input comes from the source OSM
    return {"status": "NOT_IMPLEMENTED"}


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/rq1a_osm2odr.py <run_index> [<output_base_dir>]", file=sys.stderr)
        sys.exit(1)

    run_idx = int(sys.argv[1])
    base = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/rq1a_runs")
    out_base = base / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    # For RQ1A, we need the source OSM from the pinned map
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        raise RuntimeError(f"Map verification failed: {pinned}")
    input_sha = pinned["sha256_actual"]

    out_dir = out_base / "rq1a_osm2odr"
    out_dir.mkdir(parents=True, exist_ok=True)

    # This is a stub - full implementation requires running Osm2Odr stage in isolation
    # For now, emit a receipt that indicates the experiment structure
    receipt = {
        "schema": "rq1_run_receipt/v1",
        "run": 0,
        "mode": "A",
        "status": "NOT_IMPLEMENTED",
        "error": "RQ1A requires Osm2Odr stage isolation; see tools/rq1_trial_run.py --mode=A for full pipeline mode",
        "duration_s": 0.0,
        "input_xodr": "",
        "input_sha256": "",
        "out_dir": str(out_dir),
        "xodr_sha256": None,
        "normalized_xodr_sha256": None,
        "structural_signature": None,
        "feature_counts": None,
        "topology_counts": None,
        "output_path": str(out_dir),
        "tileset_digest": None,
        "map_acceptance_digest": None,
        "final_receipt_digest": None,
    }

    receipt_path = out_base / f"rq1a_run_00_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "run": receipt["run"], "mode": receipt["mode"]}, indent=2))


if __name__ == "__main__":
    main()