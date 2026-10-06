"""Detached launcher for one cold RQ1B run (isolated dirs/cache, unbuffered log)."""
import os, sys, traceback
from pathlib import Path

run_idx = int(sys.argv[1])
base = Path("reports/rq1b_runs")
run_dir = base / f"run_{run_idx:02d}"
tmp = run_dir / "tmp"
cache_root = run_dir / "cache_root"
tmp.mkdir(parents=True, exist_ok=True)
cache_root.mkdir(parents=True, exist_ok=True)

os.environ["TMP"] = str(tmp.resolve())
os.environ["TEMP"] = str(tmp.resolve())
os.environ["UP_CACHE_ROOT"] = str(cache_root.resolve())
os.environ["UP_STAGE6_DIAGNOSTICS"] = "summary"
os.environ.setdefault("PYTHONUNBUFFERED", "1")

log = open(run_dir / "run.log", "a", encoding="utf-8")
log.write(f"=== launch run_{run_idx:02d} ===\n")
log.flush()
sys.stdout = log
sys.stderr = log
sys.argv = ["rq1_complete_receipt.py", str(run_idx), str(base)]
sys.path.insert(0, ".")
os.chdir(".")
try:
    import runpy
    runpy.run_path("tools/rq1_complete_receipt.py", run_name="__main__")
except SystemExit as e:
    log.write(f"=== exit {e.code} ===\n")
    raise
except BaseException:
    traceback.print_exc()
    raise
