#!/usr/bin/env python3
"""Run the offline pytest suite in a fully isolated environment.

Isolation is the whole point of this tool. The earlier "131 false new
failures" comparison was invalid because concurrent runs shared temp state,
pytest cache and output directories. This runner gives every invocation its
own TMP/TEMP/TMPDIR, its own pytest cache directory, its own working
directory and its own output roots, so two runs can never contaminate each
other even if started at the same moment.

Usage:
    python tools/run_isolated_regression.py --tree <path> --label <name> \
        --out <json path>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def isolated_env(root: Path, tmp: Path, cache: Path) -> Dict[str, str]:
    for d in (tmp, cache, tmp / "pipeline_out", tmp / "hpc", tmp / "logs"):
        d.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp),
        "TMPDIR": str(tmp),
        "UP_PIPELINE_OUT_DIR": str(tmp / "pipeline_out"),
        "UP_COORDINATES_JSON": str(tmp / "coordinates.json"),
        "UP_LOG_DIR": str(tmp / "logs"),
        "PYTHONDONTWRITEBYTECODE": "1",
        # Never let a caller's PYTEST_ADDOPTS or plugin autoload leak in.
        "PYTEST_ADDOPTS": "",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "0",
    })
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def parse(report: str) -> Dict[str, Any]:
    passed = failed = skipped = errors = xfailed = xpassed = 0
    m = re.search(r"(\d+) passed", report)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", report)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) skipped", report)
    if m:
        skipped = int(m.group(1))
    m = re.search(r"(\d+) errors?", report)
    if m:
        errors = int(m.group(1))
    m = re.search(r"(\d+) xfailed", report)
    if m:
        xfailed = int(m.group(1))
    m = re.search(r"(\d+) xpassed", report)
    if m:
        xpassed = int(m.group(1))
    failed_ids = sorted(set(re.findall(r"^(?:FAILED|ERROR)\s+(\S+)", report, re.M)))
    summary = ""
    for raw in reversed(report.splitlines()):
        s = raw.strip()
        if s.startswith("=") and ("passed" in s or "failed" in s or "error" in s):
            summary = s.strip("= ")
            break
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "errors": errors, "xfailed": xfailed, "xpassed": xpassed,
            "failed_or_error_test_ids": failed_ids,
            "summary_line": summary}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--marker-expr", default="not carla")
    ap.add_argument("--timeout", type=int, default=10800)
    args = ap.parse_args()

    tree = Path(args.tree).resolve()
    sandbox = Path(tempfile.mkdtemp(prefix=f"regr_{args.label}_"))
    cache = sandbox / "pytest_cache"
    env = isolated_env(tree, sandbox / "tmp", cache)

    cmd = [sys.executable, "-m", "pytest",
           "-q", "--tb=no", "-rf", "-p", "no:cacheprovider",
           "-p", "no:randomly",
           "-m", args.marker_expr,
           f"--rootdir={tree}",
           str(tree)]
    started = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(tree), env=env, timeout=args.timeout,
                           capture_output=True, text=True)
        report = r.stdout + "\n" + r.stderr
        rc = r.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        report = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(report, bytes):
            report = report.decode("utf-8", "replace")
        rc = None
        timed_out = True

    duration = time.time() - started
    parsed = parse(report)
    git = lambda *a: subprocess.run(["git", *a], cwd=str(tree),
                                    capture_output=True, text=True).stdout.strip()

    doc: Dict[str, Any] = {
        "schema": "ISOLATED_REGRESSION_RUN/v1",
        "label": args.label,
        "tree": str(tree),
        "git_head": git("rev-parse", "HEAD"),
        "git_tree": git("rev-parse", "HEAD^{tree}"),
        "dirty": bool(git("status", "--porcelain")),
        "command": " ".join(cmd),
        "marker_expr": args.marker_expr,
        "isolated": {
            "TMP": env["TMP"], "TEMP": env["TEMP"],
            "pytest_cache": str(cache),
            "cwd": str(tree),
            "pipeline_out": env["UP_PIPELINE_OUT_DIR"],
        },
        "returncode": rc,
        "timed_out": timed_out,
        "duration_s": round(duration, 2),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **parsed,
        "raw_report_tail": report[-4000:],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{args.label}: passed={parsed['passed']} failed={parsed['failed']} "
          f"errors={parsed['errors']} skipped={parsed['skipped']} "
          f"duration={doc['duration_s']}s -> {out}")
    shutil.rmtree(sandbox, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())