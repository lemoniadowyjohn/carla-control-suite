"""Deterministic sharded runner for a pytest path set.

A monolithic run exceeds the execution budget, which is an orchestration
limit, not a test failure. This partitions the collected test FILES into
contiguous deterministic shards and runs each with its own timeout, so a
slow shard is isolated and can be split further without losing the rest.

Nothing is skipped for speed: every test file lands in exactly one shard.

Usage:
    python scripts/run_unit_shards.py                 # default: tests/unit
    python scripts/run_unit_shards.py tests ultimate_pipeline

Paths are resolved against ROOT (derived from this file's location, so the
runner works from any worktree) and are either directories (recursed for
test_*.py) or single test files. Shards are written to reports/ so every
run leaves an evidence trail.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "FULL_UNIT_SUITE_SHARDS.json")
SHARD_TIMEOUT_S = 1500          # per-shard wall budget
SHARD_SIZE = 12                 # files per shard

env = dict(os.environ)
env["PYTHONDONTWRITEBYTECODE"] = "1"


def _scan(base_rel):
    """Every test_*.py under base_rel, returned as repo-relative paths."""
    found = []
    base = os.path.join(ROOT, base_rel)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", ".pytest_cache")]
        for name in sorted(filenames):
            if name.startswith("test_") and name.endswith(".py"):
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, ROOT))
    return found


def collect(paths):
    if not paths:
        return _scan(os.path.join("tests", "unit"))
    files = []
    for p in paths:
        p = p.rstrip("/\\")
        abs_p = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if os.path.isdir(abs_p):
            files.extend(_scan(os.path.relpath(abs_p, ROOT)))
        else:
            files.append(os.path.relpath(abs_p, ROOT))
    return sorted(set(files))


def parse_counts(text):
    """Pull passed/failed/skipped/error counts out of pytest output."""
    out = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
    m = re.search(r"(\d+) passed", text)
    if m:
        out["pass"] = int(m.group(1))
    m = re.search(r"(\d+) failed", text)
    if m:
        out["fail"] = int(m.group(1))
    m = re.search(r"(\d+) skipped", text)
    if m:
        out["skip"] = int(m.group(1))
    m = re.search(r"(\d+) error", text)
    if m:
        out["error"] = int(m.group(1))
    return out


def main():
    paths = [p for p in sys.argv[1:] if not p.startswith("-")]
    files = collect(paths)
    shards = [files[i:i + SHARD_SIZE]
              for i in range(0, len(files), SHARD_SIZE)]
    result = {
        "schema": "FULL_UNIT_SUITE_SHARDS/v1",
        "root": ROOT,
        "requested_paths": paths or [os.path.join("tests", "unit")],
        "shard_size_files": SHARD_SIZE,
        "shard_timeout_s": SHARD_TIMEOUT_S,
        "total_files": len(files),
        "shard_count": len(shards),
        "shards": [],
        "aggregate": None,
    }
    # Persist incrementally so a batch abort still leaves evidence.
    def flush():
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)

    flush()
    for i, shard in enumerate(shards, 1):
        t0 = time.time()
        rec = {"index": i, "files": list(shard),
               "n_files": len(shard)}
        try:
            p = subprocess.run(
                [sys.executable, "-m", "pytest", *shard, "-q",
                 "-p", "no:cacheprovider", "--tb=no", "-rN"],
                cwd=ROOT, env=env, capture_output=True, text=True,
                timeout=SHARD_TIMEOUT_S)
            rec["exit_code"] = p.returncode
            rec["counts"] = parse_counts(p.stdout + p.stderr)
            rec["timeout"] = False
            if rec["exit_code"] not in (0, 1):
                rec["stdout_tail"] = (p.stdout + p.stderr)[-1500:]
        except subprocess.TimeoutExpired as e:
            rec["exit_code"] = None
            rec["counts"] = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
            rec["timeout"] = True
            rec["stdout_tail"] = ((e.stdout or b"").decode("utf-8", "replace")
                                  if isinstance(e.stdout, bytes)
                                  else (e.stdout or ""))[-1500:]
            rec["timeout_action_required"] = "split_this_shard_further"
        rec["duration_s"] = round(time.time() - t0, 2)
        result["shards"].append(rec)
        agg = {"pass": 0, "fail": 0, "skip": 0, "error": 0}
        for s in result["shards"]:
            for k in agg:
                agg[k] += s["counts"][k]
        result["aggregate"] = agg
        flush()
        print("shard %2d/%d  %-52s pass=%-4d fail=%-3d skip=%-3d %6.1fs%s"
              % (i, len(shards), ",".join(rec["files"])[:52],
                 rec["counts"]["pass"], rec["counts"]["fail"],
                 rec["counts"]["skip"], rec["duration_s"],
                 "  TIMEOUT" if rec["timeout"] else ""))

    a = result["aggregate"]
    timed_out = [s["index"] for s in result["shards"] if s["timeout"]]
    result["timed_out_shards"] = timed_out
    result["all_shards_completed"] = not timed_out
    result["FULL_UNIT_TOTAL"] = a["pass"] + a["fail"] + a["skip"] + a["error"]
    result["FULL_UNIT_PASS"] = a["pass"]
    result["FULL_UNIT_FAIL"] = a["fail"] + a["error"]
    result["FULL_UNIT_SKIP"] = a["skip"]
    result["FULL_UNIT_SUITE"] = (
        "PASS" if (a["fail"] + a["error"]) == 0 and not timed_out
        else "INCOMPLETE")
    result["incomplete_reason"] = (
        None if result["FULL_UNIT_SUITE"] == "PASS"
        else ("shards timed out: %s" % timed_out if timed_out
              else "%d failing" % (a["fail"] + a["error"])))
    flush()
    print("\nTOTAL=%d PASS=%d FAIL=%d SKIP=%d  FULL_UNIT_SUITE=%s"
          % (result["FULL_UNIT_TOTAL"], result["FULL_UNIT_PASS"],
             result["FULL_UNIT_FAIL"], result["FULL_UNIT_SKIP"],
             result["FULL_UNIT_SUITE"]))


if __name__ == "__main__":
    main()
