# Single full-pipeline trial run against the pinned map-of-record (RQ1 N=5
# determinism matrix). Rescued 2026-10-01 -- this script produced
# reports/final_hardening_p11/run_00_receipt.json (commit 197b574c) but was
# never itself committed; it sat in a local temp directory. Recovered
# byte-for-byte from C:\Users\admin\AppData\Local\Temp\opencode\rq1_trial_run.py.
#
# Usage: python tools/rq1_trial_run.py <run_index> [<output_base_dir>]
#
# NOTE: this script's own output (status/error/duration/input_sha256/out_dir)
# is NOT yet the full rq1_run_receipt/v1 schema tools/rq1_five_run_matrix.py
# expects (xodr_sha256, normalized_xodr_sha256, structural_signature,
# feature_counts, topology_counts, per-stage hashes, etc.) -- run_00's real
# receipt was produced by additional post-processing on top of this script's
# raw run, not by this script alone. A follow-up run must still hash each
# stage's output into that schema; this script only drives the pipeline run
# itself and records pass/fail + duration + the resolved input SHA256.
import copy
import json
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
import os
os.chdir(str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.main_pipeline import MainPipeline


def main() -> None:
    pinned = verify_pinned_map("auto_map_of_record")
    assert pinned.get("verification_status") == "VERIFIED", pinned
    in_xodr = pinned["resolved_path"]

    run_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    base = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("reports/rq1_trial_runs")
    out_base = base / f"run_{run_idx:02d}"
    out_base.mkdir(parents=True, exist_ok=True)

    s = copy.copy(SETTINGS)
    s.INPUT_XODR = in_xodr
    s.BASE_OUTPUT_DIR = str(out_base)
    s.QA_AUTOVIS = False

    import time
    t0 = time.time()
    try:
        out_dir = MainPipeline(settings=s).run()
        status = "ok"
        error = ""
    except Exception as e:
        out_dir = str(out_base)
        status = f"FAILED: {type(e).__name__}: {e}"
        error = str(e)[:500]
    dur = time.time() - t0
    rec = {
        # NEW-346: declare the receipt schema tools/rq1_five_run_matrix.py
        # validates, so a raw trial run receipt is comparable without the
        # historical post-processing step.
        "schema": "rq1_run_receipt/v1",
        "run": run_idx,
        "status": status,
        "error": error,
        "duration_s": round(dur, 1),
        "input_xodr": in_xodr,
        "input_sha256": pinned["sha256_actual"],
        "out_dir": str(out_dir),
    }
    # NEW-338: the registry declares receipt_run_XX.json as this signal's
    # artifact, but the script only ever *printed* the receipt -- nothing wrote
    # the file, so the artifact was dead for every consumer.
    try:
        receipt_path = Path(out_dir) / f"receipt_run_{run_idx:02d}.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        rec["receipt_path"] = str(receipt_path)
        receipt_path.write_text(
            json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        rec["receipt_written"] = True
        print(f"receipt -> {receipt_path}")
    except Exception as exc:  # noqa: BLE001
        rec["receipt_written"] = False
        rec["receipt_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
