#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tile QA batch runner (crash-isolated).

Design:
- This module acts as a SUPERVISOR and MUST NOT import `carla`.
- Each tile is validated in a worker subprocess that imports `carla`.
- Returns non-zero if any tile fails, so callers can decide allow/deny.

This exists to satisfy:
- STEP 9 subprocess tile QA path in main_pipeline.py (python -m ultimate_pipeline.tools.tile_qa_batch ...)
- Unit tests that expect the module to exist and be invokable.

It writes:
  <out_dir>/tile_results.jsonl
  <out_dir>/tile_results.csv
  <out_dir>/tile_results.summary.json
  <out_dir>/<tile_id>.qa.json
  <out_dir>/<tile_id>.worker.log
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, List

WIN_HARD_CRASH_CODES = {
    -1073740791,  # 0xC0000409
    -1073741819,  # 0xC0000005
}

def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(path)

def _tail_text(path: Path, n: int = 4000) -> Optional[str]:
    if not path.exists():
        return None
    data = path.read_bytes()
    return data[-n:].decode("utf-8", errors="replace")

@dataclass
class TileRunResult:
    tile_id: str
    tile_path: str
    ok: bool
    reason: str
    worker_returncode: Optional[int]
    seconds: float
    output_json: Optional[str]
    log_path: Optional[str]
    log_tail: Optional[str]

def _run_worker(tile_id: str, tile_path: Path, out_dir: Path, host: str, port: int, timeout_s: float, no_spawn: bool, strict: bool) -> TileRunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{tile_id}.qa.json"
    log_path = out_dir / f"{tile_id}.worker.log"

    env = os.environ.copy()
    env["PYTHONFAULTHANDLER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable, "-u", "-m", "ultimate_pipeline.tile_validation.step10_tile_qa_worker",
        "--tile-id", tile_id,
        "--xodr", str(tile_path),
        "--out-json", str(out_json),
        "--host", host,
        "--port", str(port),
        "--timeout-s", str(timeout_s),
        "--no-spawn", "1" if no_spawn else "0",
        "--strict", "1" if strict else "0",
    ]

    t0 = time.time()
    try:
        with open(log_path, "ab", buffering=0) as f:
            p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=timeout_s, check=False)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = 124
    dt = time.time() - t0

    ok = False
    reason = "unknown"
    if rc == 0 and out_json.exists():
        try:
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            ok = bool(payload.get("ok", False))
            reason = payload.get("reason", "ok" if ok else "worker_reported_failure")
        except Exception as e:
            ok = False
            reason = f"invalid_output_json: {e!r}"
    else:
        if rc == 124:
            reason = "worker_timeout"
        elif rc in WIN_HARD_CRASH_CODES:
            reason = f"worker_native_crash_rc={rc}"
        else:
            reason = f"worker_failed_rc={rc}"

    return TileRunResult(
        tile_id=tile_id,
        tile_path=str(tile_path),
        ok=ok,
        reason=reason,
        worker_returncode=rc,
        seconds=round(dt, 3),
        output_json=str(out_json) if out_json.exists() else None,
        log_path=str(log_path) if log_path.exists() else None,
        log_tail=_tail_text(log_path),
    )


def _run_tile_worker(
    *,
    python_exe: str,
    tile_xodr: Path,
    report_path: Path,
    log_path: Path,
    timeout_s: float,
    retries: int,
    fix_s: bool,
    no_spawn: bool,
) -> int:
    """Legacy/test-facing worker launcher.

    Unit tests expect:
      - a function named `_run_tile_worker`
      - a `--no_spawn` flag (underscore) forwarded when `no_spawn=True`
      - `UP_NO_CARLA_AUTOSTART=1` in the worker env when `no_spawn=True`
    """
    env = os.environ.copy()
    if no_spawn:
        env["UP_NO_CARLA_AUTOSTART"] = "1"

    cmd = [
        python_exe,
        "-u",
        "-m",
        "ultimate_pipeline.tile_validation.step10_tile_qa_worker",
        "--xodr",
        str(tile_xodr),
        "--out-json",
        str(report_path),
    ]
    if fix_s:
        cmd += ["--fix-s"]
    if no_spawn:
        cmd += ["--no_spawn"]

    attempts = max(1, int(retries) + 1)
    rc = 1
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        try:
            with open(log_path, "ab") as f:
                res = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=float(timeout_s))
            rc = int(getattr(res, "returncode", 1) or 0)
        except subprocess.TimeoutExpired:
            rc = 124
        if rc == 0:
            break
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tile_metadata", default="")
    ap.add_argument("--tiles_dir", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--host", default=os.getenv("UP_CARLA_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("UP_CARLA_PORT", "2000")))
    ap.add_argument("--timeout_s", type=float, default=180.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--max_tile_attempts", type=int, default=2)
    ap.add_argument("--restart_every_n", type=int, default=10)
    ap.add_argument("--fix_s", action="store_true")
    ap.add_argument("--no_spawn", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    tiles_dir = Path(args.tiles_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # enumerate tiles
    tile_paths = sorted(tiles_dir.glob("*.xodr"))
    if not tile_paths:
        tile_paths = sorted(tiles_dir.glob("tile_*.xodr"))

    if not tile_paths:
        _atomic_write_json(out_dir / "tile_results.summary.json", {"ok": False, "reason": "no_tiles_found", "tiles_dir": str(tiles_dir)})
        return 3

    jsonl_path = out_dir / "tile_results.jsonl"
    csv_path = out_dir / "tile_results.csv"
    summary_path = out_dir / "tile_results.summary.json"

    header = list(asdict(TileRunResult(
        tile_id="",
        tile_path="",
        ok=False,
        reason="",
        worker_returncode=None,
        seconds=0.0,
        output_json=None,
        log_path=None,
        log_tail=None,
    )).keys())
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=header).writeheader()

    rows: List[Dict[str, Any]] = []
    any_fail = False

    for tile_path in tile_paths:
        tile_id = tile_path.stem
        attempts = 0
        best: Optional[TileRunResult] = None

        max_attempts = max(1, int(args.max_tile_attempts))
        while attempts < max_attempts:
            attempts += 1
            r = _run_worker(
                tile_id=tile_id,
                tile_path=tile_path,
                out_dir=out_dir,
                host=args.host,
                port=args.port,
                timeout_s=float(args.timeout_s),
                no_spawn=bool(args.no_spawn) or True,  # default to True even if flag omitted
                strict=bool(args.strict),
            )
            best = r
            # success on first ok
            if r.ok:
                break

        assert best is not None
        row = asdict(best)
        row["attempts"] = attempts
        rows.append(row)

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=header + ["attempts"]).writerow(row)

        if not best.ok:
            any_fail = True

    summary = {
        "ok": not any_fail,
        "total": len(rows),
        "passed": sum(1 for r in rows if r["ok"]),
        "failed": sum(1 for r in rows if not r["ok"]),
        "tiles_dir": str(tiles_dir),
        "out_dir": str(out_dir),
        "timeout_s": float(args.timeout_s),
        "no_spawn": True,
        "strict": bool(args.strict),
        "note": "This runner is crash-isolated; CARLA native crashes are counted as failures.",
    }
    _atomic_write_json(summary_path, summary)

    # Return non-zero if any tile failed so callers can apply allow-fail policy
    return 0 if summary["ok"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
