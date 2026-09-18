#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crash-proof STEP 10 Unified Tile QA Supervisor (PARENT)

Changes in this patch:
- Prints progress to stdout (captured by caller into step10_tile_qa_supervisor.log)
  so it’s obvious the batch is running.
- Still NEVER imports `carla` and remains crash-isolating.

Artifacts:
- tile_results.jsonl / tile_results.csv / tile_results.summary.json / tile_qa_status.json
- per-tile worker logs and per-tile JSON reports
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
    did_restart_carla: bool

class CarlaServerManager:
    def __init__(self, carla_exe: Optional[str], port: int, log_path: Path, extra_args: Optional[List[str]] = None):
        self.carla_exe = carla_exe
        self.port = int(port)
        self.log_path = log_path
        self.extra_args = extra_args or []
        self.proc: Optional[subprocess.Popen] = None
        self._log_fh = None

    def can_manage(self) -> bool:
        return bool(self.carla_exe)

    def start(self) -> None:
        if not self.can_manage():
            return
        self.stop()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = open(self.log_path, "ab", buffering=0)

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)

        cmd = [str(self.carla_exe), f"-carla-rpc-port={self.port}", *self.extra_args]
        self.proc = subprocess.Popen(cmd, stdout=self._log_fh, stderr=self._log_fh, creationflags=creationflags)

    def is_running(self) -> bool:
        if not self.can_manage():
            return True
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True, text=True)
            else:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        self.proc = None
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None

    def restart(self) -> bool:
        if not self.can_manage():
            return False
        self.stop()
        time.sleep(1.0)
        self.start()
        return True

def _run_worker(tile_id: str, tile_path: Path, out_dir: Path, host: str, port: int, timeout_s: int, no_spawn: bool, strict: bool) -> TileRunResult:
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
        did_restart_carla=False,
    )

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles_dir", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout_s", type=int, default=180)
    ap.add_argument("--restart_after_consecutive_failures", type=int, default=5)
    ap.add_argument("--restart_on_hard_crash", type=int, default=1)
    ap.add_argument("--no_spawn", type=int, default=1)
    ap.add_argument("--strict", type=int, default=0)
    ap.add_argument("--carla_exe", default="")
    ap.add_argument("--carla_extra_args", nargs="*", default=[])
    args = ap.parse_args()

    tiles_dir = Path(args.tiles_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tile_paths = sorted(tiles_dir.glob("tile_*.xodr")) or sorted(tiles_dir.glob("*.xodr"))
    if not tile_paths:
        _atomic_write_json(out_dir / "tile_qa_status.json", {"status": "FAIL", "reason": "no_tiles_found", "tiles_dir": str(tiles_dir)})
        print("[STEP10_SUP] no tiles found; exiting", flush=True)
        return 0

    jsonl_path = out_dir / "tile_results.jsonl"
    csv_path = out_dir / "tile_results.csv"
    summary_path = out_dir / "tile_results.summary.json"
    status_path = out_dir / "tile_qa_status.json"

    mgr = CarlaServerManager(
        carla_exe=args.carla_exe.strip() or None,
        port=args.port,
        log_path=out_dir / "carla_server_step10.log",
        extra_args=list(args.carla_extra_args or []),
    )
    if mgr.can_manage():
        print(f"[STEP10_SUP] starting CARLA server: {args.carla_exe}", flush=True)
        mgr.start()

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
        did_restart_carla=False,
    )).keys())
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=header).writeheader()

    print(f"[STEP10_SUP] tiles={len(tile_paths)} host={args.host} port={args.port} no_spawn={bool(args.no_spawn)} strict={bool(args.strict)}", flush=True)

    consecutive_failures = 0
    rows: List[Dict[str, Any]] = []

    for i, tile_path in enumerate(tile_paths, start=1):
        tile_id = tile_path.stem
        print(f"[STEP10_SUP] ({i}/{len(tile_paths)}) start tile={tile_id}", flush=True)

        r = _run_worker(
            tile_id=tile_id,
            tile_path=tile_path,
            out_dir=out_dir,
            host=args.host,
            port=args.port,
            timeout_s=int(args.timeout_s),
            no_spawn=bool(args.no_spawn),
            strict=bool(args.strict),
        )
        row = asdict(r)
        rows.append(row)

        if r.ok:
            consecutive_failures = 0
        else:
            consecutive_failures += 1

        should_restart = False
        if bool(args.restart_on_hard_crash) and (r.worker_returncode in WIN_HARD_CRASH_CODES):
            should_restart = True
        if consecutive_failures >= int(args.restart_after_consecutive_failures):
            should_restart = True
        if isinstance(r.reason, str) and "not_ready" in r.reason:
            should_restart = True

        if should_restart:
            did = mgr.restart()
            print(f"[STEP10_SUP] restart_carla={did} after consecutive_failures={consecutive_failures}", flush=True)
            consecutive_failures = 0

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=header).writerow(row)

        print(f"[STEP10_SUP] ({i}/{len(tile_paths)}) done tile={tile_id} ok={r.ok} reason={r.reason} rc={r.worker_returncode} t={r.seconds}s", flush=True)

    summary = {
        "total": len(rows),
        "ok": sum(1 for x in rows if x["ok"]),
        "fail": sum(1 for x in rows if not x["ok"]),
        "no_spawn": bool(args.no_spawn),
        "strict": bool(args.strict),
        "timeout_s": int(args.timeout_s),
        "restart_after_consecutive_failures": int(args.restart_after_consecutive_failures),
        "restart_on_hard_crash": bool(args.restart_on_hard_crash),
        "hard_crash_codes": sorted(WIN_HARD_CRASH_CODES),
        "tiles_dir": str(tiles_dir),
        "carla_exe": args.carla_exe.strip() or None,
    }
    _atomic_write_json(summary_path, summary)
    _atomic_write_json(status_path, {"status": "OK", "summary_path": str(summary_path), "summary": summary})

    print(f"[STEP10_SUP] done: ok={summary['ok']} fail={summary['fail']} -> {summary_path}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
