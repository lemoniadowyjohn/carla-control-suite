#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RQ1B: Pinned XODR -> Full Downstream Pipeline Determinism (N>=5)

Repeats the full downstream pipeline from a pinned XODR through all stages
to final map-of-record. Each run must produce identical RQ1 identities:
(raw XODR sha256, canonical normalized XODR identity, structural signature,
feature/topology counts, tileset digest, map_acceptance digest,
final_receipt_digest).

Exit-code authority (fix): the child process exits NON-ZERO whenever the
governed pipeline experiment fails, even though the receipt is still
written first (status = FAILED, process exit != 0).

Identities (fix): ``normalized_xodr_sha256`` is no longer aliased to the
raw final-XODR sha; it is produced by the versioned canonical OpenDRIVE
normalization used ONLY for the frozen RQ1 metric
(research/rq1_normalization.py).  ``structural_signature`` is a real
versioned network-structure signature (research/rq1_structural_signature.py).

Usage:
    python tools/rq1b_full_pipeline.py <run_index> [<output_base_dir>]

Schema: rq1_run_receipt/v2
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

from research.evidence.canonical import git_head_sha, is_dirty_worktree, safe_env_record
from research.evidence.schemas import RESEARCH_CONTRACT_SHA256
from research.rq1_normalization import NORMALIZATION_VERSION, normalize_xodr
from research.rq1_structural_signature import STRUCTURAL_SIGNATURE_VERSION, compute_structural_signature
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.main_pipeline import MainPipeline
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance
from ultimate_pipeline.quality.map_acceptance import safe_sha256_file

RECEIPT_SCHEMA = "rq1_run_receipt/v2"


def _sha256_dict(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _digest_file(path: Optional[str]) -> Optional[str]:
    if path and os.path.exists(path):
        return safe_sha256_file(path)
    return None


def _extract_structural_signature(map_acceptance: Dict[str, Any]) -> Optional[str]:
    """(legacy field) map-acceptance payload SHA - retained for continuity."""
    return map_acceptance.get("payload_sha256")


def _extract_feature_counts(map_acceptance: Dict[str, Any]) -> Optional[Dict[str, int]]:
    if not map_acceptance:
        return None
    metrics = map_acceptance.get("metrics", {})
    return {
        k: v
        for k, v in metrics.items()
        if isinstance(v, int)
        and any(
            kw in k.lower()
            for kw in ["count", "buildings", "signals", "traffic_light", "lane", "junction", "road", "building"]
        )
    }


def _extract_topology_counts(map_acceptance: Dict[str, Any]) -> Optional[Dict[str, int]]:
    if not map_acceptance:
        return None
    metrics = map_acceptance.get("metrics", {})
    return {
        k: v
        for k, v in metrics.items()
        if isinstance(v, int)
        and any(
            kw in k.lower()
            for kw in [
                "component",
                "lane",
                "junction",
                "road",
                "lane_width",
                "elevation",
                "seam",
                "smoothness",
                "physics",
                "origin",
                "lane_geometry",
                "physics_feas",
            ]
        )
    }


def _extract_tileset_digest(map_acceptance: Dict[str, Any]) -> Optional[str]:
    if not map_acceptance:
        return None
    return map_acceptance.get("linked_artifact_sha256", {}).get("tileset_digest")


def _settings_digest(s: Any) -> str:
    blob = json.dumps(
        {k: getattr(s, k) for k in dir(s) if k.isupper() and not callable(getattr(s, k))},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _effective_env_record(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Effective environment identity (secrets excluded/masked).

    Only governed variables + the whitelisted system base are present at
    run time (the driver builds a whitelist env); this record proves it.
    """
    full = dict(os.environ) if env is None else dict(env)
    record = safe_env_record(full)
    return {
        "schema": "rq1_effective_env/v1",
        "governed": {k: v for k, v in record.items() if k.startswith("UP_")},
        "system_allowlist": {
            k: v for k, v in record.items() if not k.startswith("UP_")
        },
        "policy": "driver supplies whitelist env; secrets masked; full key list recorded",
    }


def _input_identities(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = dict(os.environ) if env is None else dict(env)
    pinned = {
        "OSM": "UP_OSM_FILE",
        "BUILDINGS": "UP_PINNED_BUILDINGS_SOURCE",
    }
    out: Dict[str, Any] = {}
    for label, var in pinned.items():
        p = env.get(var, "").strip()
        if p:
            entry: Dict[str, Any] = {"path": p}
            if os.path.isfile(p):
                entry["sha256"] = safe_sha256_file(p)
            else:
                entry["available"] = False
            out[label] = entry
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python tools/rq1b_full_pipeline.py <run_index> [<output_base_dir>]",
            file=sys.stderr,
        )
        return 2

    run_idx = int(sys.argv[1])
    base = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/rq1b_runs")
    out_base = base / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    # Verify pinned map
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        print(f"FATAL: map verification failed: {pinned}", file=sys.stderr)
        return 2
    in_xodr = pinned["resolved_path"]
    input_sha = pinned["sha256_actual"]

    out_dir = out_base / "rq1b_full"
    out_dir.mkdir(parents=True, exist_ok=True)

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = in_xodr
    s.BASE_OUTPUT_DIR = str(out_dir)
    s.QA_AUTOVIS = False
    settings_digest = _settings_digest(s)

    t0 = time.time()
    try:
        pipeline = MainPipeline(settings=s)
        out_dir_str = pipeline.run()
        status = "ok"
        error = ""
        map_acceptance = getattr(pipeline, "map_acceptance", {})
    except Exception as e:
        out_dir_str = str(out_dir)
        status = "FAILED"
        error = f"{type(e).__name__}: {e}"[:500]
        map_acceptance = {}
    dur = time.time() - t0

    # ---- RQ1 identities from the FINAL artifact produced by the pipeline
    final_xodr = map_acceptance.get("final_xodr_path") if map_acceptance else None
    final_xodr_sha = _digest_file(final_xodr) if final_xodr else None
    if final_xodr and os.path.isfile(final_xodr):
        normalized = normalize_xodr(final_xodr)
        normalized_xodr_sha = normalized["sha256"]
        signature = compute_structural_signature(
            final_xodr, store_payload=out_base / "rq1b_structural_payload.json"
        )
        structural_signature = signature["sha256"]
        structural_meta = {
            "version": signature["version"],
            "road_count": signature["road_count"],
            "junction_count": signature["junction_count"],
            "payload_sha256": signature["payload_sha256"],
            "payload_path": signature["payload_path"],
        }
    else:
        normalized_xodr_sha = None
        structural_signature = None
        structural_meta = None

    receipt: Dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "run": run_idx,
        "mode": "B",
        "status": status,
        "error": error,
        "duration_s": round(dur, 1),
        "input_xodr": in_xodr,
        "input_sha256": input_sha,
        "out_dir": str(out_dir_str),
        "xodr_sha256": final_xodr_sha,
        "normalized_xodr_sha256": normalized_xodr_sha,
        "normalized_identity_version": NORMALIZATION_VERSION,
        "structural_signature": structural_signature,
        "structural_signature_version": STRUCTURAL_SIGNATURE_VERSION,
        "structural_meta": structural_meta,
        "feature_counts": _extract_feature_counts(map_acceptance),
        "topology_counts": _extract_topology_counts(map_acceptance),
        "output_path": str(out_dir),
        "tileset_digest": _extract_tileset_digest(map_acceptance),
        "map_acceptance_digest": map_acceptance.get("payload_sha256") if map_acceptance else None,
        "final_receipt_digest": map_acceptance.get("acceptance_artifact_sha256") if map_acceptance else None,
        # evidence-authority bindings
        "git_sha": git_head_sha(WORKTREE),
        "source_dirty": is_dirty_worktree(WORKTREE),
        "settings_digest": settings_digest,
        "effective_env": _effective_env_record(),
        "inputs_record": _input_identities(),
        "rq_contract_sha256": RESEARCH_CONTRACT_SHA256,
        "seeds": [],
        # legacy continuity fields retained (map-acceptance payload scope)
        "legacy_structural_signature": _extract_structural_signature(map_acceptance),
        "map_acceptance": map_acceptance,
    }

    receipt_path = Path(out_base) / f"rq1b_run_{run_idx:02d}_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": receipt["status"], "run": receipt["run"], "mode": receipt["mode"]},
            indent=2,
        ),
        flush=True,
    )
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
