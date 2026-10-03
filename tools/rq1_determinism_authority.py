#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1 Determinism Authority — Single artifact producing the final RQ1 verdict.

Consumes:
  - RQ1A receipts (pinned OSM -> Osm2Odr, N>=5 runs)
  - RQ1B receipts (pinned XODR -> full pipeline, N>=5 runs)

Produces:
  - rq1_determinism_verdict/v1 with PASS/FAIL/INCOMPLETE
  - Evidence: per-field mismatch tables, run count, schema version
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load_receipt(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != "rq1_run_receipt/v1":
            return {"status": "INVALID_SCHEMA", "path": str(path)}
        return {"status": "OK", "data": data}
    except Exception as e:
        return {"status": "UNREADABLE", "path": str(path), "reason": str(e)}


def _compare_field_across_runs(runs: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    """Compare a field across all runs, return mismatch info if any."""
    values = []
    for run in runs:
        if run.get("status") != "OK":
            return {"field": field, "status": "INCOMPLETE", "reason": "some runs unreadable"}
        val = run["data"].get(field)
        values.append(json.dumps(val, sort_keys=True, separators=(",", ":")) if val is not None else "null")
    unique = set(values)
    if len(unique) > 1:
        return {"field": field, "status": "MISMATCH", "values": values}
    return {"field": field, "status": "MATCH", "value": values[0]}


REPO_ROOT = Path(__file__).resolve().parents[1]


def _receipts_from_matrix(matrix_path: Path) -> List[Path]:
    """Resolve receipt paths from an explicit five-run matrix document.

    Batch 14 section 5: the closure aggregator previously depended on however
    the caller happened to glob for receipts, which silently produced
    ``rq1a_count = 1``. The matrix path is now an explicit input, so the
    evidence set is declared rather than discovered.
    """
    doc = json.loads(Path(matrix_path).read_text(encoding="utf-8"))
    # The RQ1A matrix (wave A) and the RQ1B matrix (wave B) use different
    # receipt list keys. Both are accepted; neither is guessed.
    receipts = (doc.get("complete_receipts") or doc.get("receipts"))
    if not isinstance(receipts, list) or not receipts:
        raise ValueError(
            f"{matrix_path} declares neither complete_receipts nor receipts; "
            "refusing to guess an evidence set")
    return [REPO_ROOT / str(r) for r in receipts]


def build_verdict(rq1a_receipts: List[Path], rq1b_receipts: List[Path]) -> Dict[str, Any]:
    # Load all receipts
    rq1a_runs = [_load_receipt(p) for p in rq1a_receipts]
    rq1b_runs = [_load_receipt(p) for p in rq1b_receipts]

    available_a = [r for r in rq1a_runs if r["status"] == "OK"]
    available_b = [r for r in rq1b_runs if r["status"] == "OK"]

    if len(available_a) < 5:
        return {
            "schema": "rq1_determinism_verdict/v1",
            "verdict": "INCOMPLETE",
            "reason": f"RQ1A requires 5 valid runs, got {len(available_a)}",
            "rq1a_count": len(available_a),
            "rq1b_count": len(available_b),
        }
    if len(available_b) < 5:
        return {
            "schema": "rq1_determinism_verdict/v1",
            "verdict": "INCOMPLETE",
            "reason": f"RQ1B requires 5 valid runs, got {len(available_b)}",
            "rq1a_count": len(available_a),
            "rq1b_count": len(available_b),
        }

    # Fields to compare (from rq1_run_receipt/v1 schema)
    fields = [
        "xodr_sha256",
        "normalized_xodr_sha256",
        "structural_signature",
        "feature_counts",
        "topology_counts",
        "output_path",
        "tileset_digest",
        "map_acceptance_digest",
        "final_receipt_digest",
    ]

    # Compare RQ1A runs
    rq1a_data = [r["data"] for r in available_a]
    rq1b_data = [r["data"] for r in available_b]

    mismatches = []
    for field in fields:
        # Compare RQ1A
        vals_a = [json.dumps(r.get(field), sort_keys=True, separators=(",", ":")) for r in rq1a_data]
        if len(set(vals_a)) > 1:
            mismatches.append({
                "experiment": "RQ1A",
                "field": field,
                "values": vals_a,
            })
        # Compare RQ1B
        vals_b = [json.dumps(r.get(field), sort_keys=True, separators=(",", ":")) for r in rq1b_data]
        if len(set(vals_b)) > 1:
            mismatches.append({
                "experiment": "RQ1B",
                "field": field,
                "values": vals_b,
            })

    # Cross-experiment comparison (RQ1A vs RQ1B should differ in some fields)
    # xodr_sha256 should differ (RQ1A: OSM->Osm2Odr output; RQ1B: pinned XODR)
    # structural_signature should match if pipeline is deterministic

    verdict = "PASS" if not mismatches else "FAIL"

    return {
        "schema": "rq1_determinism_verdict/v1",
        "verdict": verdict,
        # Every branch of this document exposes the same count keys so a
        # consumer never has to know which code path produced the verdict.
        "rq1a_count": len(available_a),
        "rq1b_count": len(available_b),
        "rq1a_run_count": len(available_a),
        "rq1b_run_count": len(available_b),
        "mismatches": mismatches,
        "comparison_policy": "No normalization of unknown fields; timestamp, ordering, floating-point, and structural differences remain observable.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rq1a", nargs="+", type=Path, default=None, help="RQ1A receipt paths (>=5)")
    parser.add_argument("--rq1b", nargs="+", type=Path, default=None, help="RQ1B receipt paths (>=5)")
    parser.add_argument("--rq1a-matrix", type=Path, default=None,
                        help="Explicit RQ1A five-run matrix; its "
                             "complete_receipts list is used instead of any glob")
    parser.add_argument("--rq1b-matrix", type=Path, default=None,
                        help="Explicit RQ1B five-run matrix; its "
                             "complete_receipts list is used instead of any glob")
    parser.add_argument("--out", type=Path, required=True, help="Output verdict JSON")
    args = parser.parse_args()

    if args.rq1a_matrix:
        rq1a = _receipts_from_matrix(args.rq1a_matrix)
    elif args.rq1a:
        rq1a = args.rq1a
    else:
        parser.error("RQ1A evidence is required: pass --rq1a-matrix or --rq1a")

    if args.rq1b_matrix:
        rq1b = _receipts_from_matrix(args.rq1b_matrix)
    elif args.rq1b:
        rq1b = args.rq1b
    else:
        parser.error("RQ1B evidence is required: pass --rq1b-matrix or --rq1b")

    verdict = build_verdict(rq1a, rq1b)
    args.out.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict["verdict"], "rq1a_runs": len(rq1a), "rq1b_runs": len(rq1b), "mismatches": len(verdict.get("mismatches", []))}, indent=2))
    return 0 if verdict["verdict"] == "PASS" else 2 if verdict["verdict"] == "FAIL" else 3


if __name__ == "__main__":
    raise SystemExit(main())