#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ1B driver: five isolated cold runs of the full downstream pipeline.

Each run is a separate OS process with:
  - its own BASE_OUTPUT_DIR (reports/rq1b_runs/run_NN)
  - its own UP_RUN_TAG (fixed per-run for determinism)
  - no shared cache: PYTHONPYCACHEPREFIX and TMPDIR are per-run
  - hermetic environment: an explicit WHITELIST base (required system
    variables only) plus the explicitly governed pipeline variables.  No
    arbitrary inherited override (UP_OUTPUT_DIR, alternate source inputs,
    network flags, alternate map/city, experimental mutation toggles,
    stale caches, alternate release profiles) can leak in.
  - all generation inputs pinned to the governed campaign sources
    (no network access, no Overpass download, no mtime/glob selection)

After all runs, the driver compares per-run identities (input identity,
raw XODR sha, canonical normalized XODR sha, structural signature, tileset
digest, map-acceptance digest, final receipt digest) and emits
``RQ1_FULL_DETERMINISM_MATRIX.json`` with per-run identities and a
deterministic divergence classification.  Mismatches are never hidden; the
driver exits non-zero unless every required run is valid and all measured
identities agree.

Emits one receipt per run (rq1_run_receipt/v2) plus the matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from research.rq1_determinism_matrix import build_determinism_matrix

EXPECTED_XODR_SHA = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"

PINNED_OSM = "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
PINNED_BUILDINGS = (
    "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json"
)

# ---------------------------------------------------------------------------
# Hermetic environment policy (fix): WHITELIST base + governed variables.
# ---------------------------------------------------------------------------
SYSTEM_WHITELIST = [
    # Windows process plumbing required to spawn/execute and locate tooling.
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "PATH",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
    "TEMP",
    "TMP",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "ALLUSERSPROFILE",
    "APPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES",
    # Python process plumbing (child is spawned by absolute interpreter path).
    "PYTHONIOENCODING",
]

# Governed pipeline variables (explicit, pinned values below).
GOVERNED_VARS = {
    "UP_OSM_FILE": lambda: str(REPO / PINNED_OSM),
    "UP_PINNED_BUILDINGS_SOURCE": lambda: str(REPO / PINNED_BUILDINGS),
    "UP_DISABLE_OSM_DOWNLOAD": lambda: "1",
    "UP_OFFLINE_ONLY": lambda: "1",
    "UP_CARLA_SAFE_MODE": lambda: "1",
    # Explicit release-profile pin (never alternate/experimental).
    "UP_RELEASE_PROFILE": lambda: "DEVELOPMENT",
    # Deterministic output naming (no wall-clock in the output path).
    "UP_RUN_TAG": None,  # per-run value
    # Determinism hardening (hash randomization off; pycache per-run below).
    "PYTHONHASHSEED": lambda: "0",
    "PYTHONPYCACHEPREFIX": None,  # per-run value
}


def build_child_env(run_dir: Path, run_idx: int) -> Dict[str, str]:
    """Whitelist child environment.  Cold runs: no shared cache between runs."""
    cache_root = run_dir / "cache"
    tmp_root = run_dir / "tmp"
    pycache_root = run_dir / "pycache"
    for d in (cache_root, tmp_root, pycache_root):
        d.mkdir(parents=True, exist_ok=True)

    inherited = os.environ
    env: Dict[str, str] = {}
    for key in SYSTEM_WHITELIST:
        if key in inherited and inherited[key]:
            env[key] = inherited[key]
    for key, value_fn in GOVERNED_VARS.items():
        if value_fn is not None:
            env[key] = value_fn()
    env["UP_RUN_TAG"] = f"rq1b_run{run_idx:02d}"
    env["PYTHONPYCACHEPREFIX"] = str(pycache_root)
    env["TEMP"] = str(tmp_root)
    env["TMP"] = str(tmp_root)
    env.setdefault("PYTHONIOENCODING", "utf-8")
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

    cmd = [sys.executable, str(REPO / "tools" / "rq1b_full_pipeline.py"), str(run_idx), str(out_base)]
    t0 = time.time()
    proc: Optional[subprocess.CompletedProcess] = None
    timed_out = False
    timeout_exc: Optional[BaseException] = None
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
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        timeout_exc = exc
    dur = time.time() - t0
    if timed_out:
        (run_dir / "child_stdout.log").write_text("", encoding="utf-8")
        (run_dir / "child_stderr.log").write_text(
            f"TIMEOUT after {dur:.0f}s (limit 7200s): {timeout_exc}", encoding="utf-8"
        )
        return_code = -1
    else:
        assert proc is not None
        (run_dir / "child_stdout.log").write_text(proc.stdout or "", encoding="utf-8")
        (run_dir / "child_stderr.log").write_text(proc.stderr or "", encoding="utf-8")
        return_code = proc.returncode

    receipts = sorted(run_dir.glob("rq1b_run_*_receipt.json"))
    receipt: Dict[str, Any] = {
        "schema": "rq1b_run_wrapper_receipt/v1",
        "run_index": run_idx,
        "run_id": f"rq1b_run{run_idx:02d}",
        "input_xodr_sha256": EXPECTED_XODR_SHA,
        "input_xodr_path": pinned["resolved_path"],
        "command": " ".join(cmd),
        "return_code": return_code,
        "timed_out": timed_out,
        "timeout_limit_s": 7200,
        "duration_s": round(dur, 1),
        "isolated": True,
        "shared_cache": False,
        "env_policy": "whitelist+governed (no inherited overrides)",
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

    run_count = len(receipts)
    valid_run_count = sum(
        1
        for r in receipts
        if r["return_code"] == 0 and r["receipt_found"] and (r.get("child_receipt") or {}).get("status") == "ok"
    )
    matrix = build_determinism_matrix(receipts, valid_run_count=valid_run_count)

    full_matrix = {
        "schema": "rq1b_five_run_matrix/v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_xodr_sha256": EXPECTED_XODR_SHA,
        "runs_requested": args.runs,
        "runs_completed": run_count,
        "valid_run_count": valid_run_count,
        "all_returncode_zero": all(r["return_code"] == 0 for r in receipts),
        "all_receipts_present": all(r["receipt_found"] for r in receipts),
        "any_timed_out": any(r.get("timed_out") for r in receipts),
        "determinism": matrix,
        "receipts": receipts,
    }
    matrix_path = out_base / "RQ1_FULL_DETERMINISM_MATRIX.json"
    matrix_path.write_text(
        json.dumps(full_matrix, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    legacy_matrix = {
        "schema": "rq1b_five_run_matrix/v1",
        "generated_at_utc": full_matrix["generated_at_utc"],
        "input_xodr_sha256": EXPECTED_XODR_SHA,
        "runs_requested": args.runs,
        "runs_completed": run_count,
        "all_returncode_zero": full_matrix["all_returncode_zero"],
        "all_receipts_present": full_matrix["all_receipts_present"],
        "any_timed_out": full_matrix["any_timed_out"],
        "receipts": receipts,
    }
    (out_base / "RQ1B_FIVE_RUN_MATRIX.json").write_text(
        json.dumps(legacy_matrix, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in full_matrix.items() if k != "receipts"}, indent=2))
    campaign_ok = (
        args.runs > 0
        and valid_run_count == args.runs
        and matrix["all_raw_equal"]
        and matrix["all_normalized_equal"]
        and matrix["all_structural_equal"]
        and matrix["divergence_classification"] == "NO_DIFFERENCE"
    )
    return 0 if campaign_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
