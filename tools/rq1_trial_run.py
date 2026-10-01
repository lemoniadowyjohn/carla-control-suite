# Single full-pipeline trial run against the pinned map-of-record (RQ1 N=5
# determinism matrix). Rescued 2026-10-01 -- this script produced
# reports/final_hardening_p11/run_00_receipt.json (commit 197b574c) but was
# never itself committed; it sat in a local temp directory. Recovered
# byte-for-byte from C:\Users\admin\AppData\Local\Temp\opencode\rq1_trial_run.py.
#
# Usage: python tools/rq1_trial_run.py <run_index> [<output_base_dir>]
#
# This script now produces a complete rq1_run_receipt/v1 receipt after each run
# by hashing stage outputs and combining with pipeline run metadata.
import copy
import json
import subprocess
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

    # Run the receipt assembler to build the full rq1_run_receipt/v1 receipt
    assembler_script = WORKTREE / "tools" / "rq1_receipt_assembler.py"
    assembler_cmd = [
        sys.executable,
        str(assembler_script),
        str(run_idx),
        str(out_base),
    ]
    assembler_result = subprocess.run(
        assembler_cmd,
        capture_output=True,
        text=True,
        cwd=str(WORKTREE),
    )
    
    if assembler_result.returncode != 0:
        print(f"WARNING: Receipt assembler failed: {assembler_result.stderr}", file=sys.stderr)
        # Fall back to basic receipt
        rec = {
            "run": run_idx,
            "status": status,
            "error": error,
            "duration_s": round(dur, 1),
            "input_xodr": in_xodr,
            "input_sha256": pinned["sha256_actual"],
            "out_dir": str(out_dir),
        }
        print(json.dumps(rec, indent=1))
    else:
        # The assembler writes the receipt file and prints a JSON summary
        # We'll forward that output
        print(assembler_result.stdout.strip())
        if assembler_result.stderr:
            print(assembler_result.stderr.strip(), file=sys.stderr)


if __name__ == "__main__":
    main()
