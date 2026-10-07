#!/usr/bin/env python3
"""Supervised governed UE run: job-owned tree + lease heartbeat + receipt.

Detached-friendly: lives for the whole operation, heartbeats the lease,
then writes a terminal receipt (exit code, Windows class, times, log SHA,
drain state). Never releases the lease (release is a separate decision).

Usage:
  python tools/supervised_ue_run.py --label PrepareAssets --run-id R \\
      --receipt reports/control_plane/PREPARE_ASSETS_RECOVERY_RECEIPT.json \\
      --log G:\\CARLA\\build_logs\\prepare_xxx.log \\
      --timeout-s 14400 --heartbeat-s 60 -- <cmd...>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ultimate_pipeline.governance.single_writer import (
    exit_codes as _ex,
    job_supervision as _job,
    lease_store as _ls,
)


def sha(p: str):
    try:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for ch in iter(lambda: fh.read(1 << 20), b""):
                h.update(ch)
        return h.hexdigest()
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--timeout-s", type=float, default=14400)
    ap.add_argument("--heartbeat-s", type=float, default=60)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    receipt = {
        "schema": "supervised_ue_run/v1",
        "label": args.label,
        "run_id": args.run_id,
        "command": cmd,
        "start_utc": _ls._utcnow(),
        "heartbeat": "lease heartbeat every %.0fs" % args.heartbeat_s,
    }
    Path(args.receipt).write_text(json.dumps(receipt, indent=1))

    job = _job.create_job()
    log_fh = open(args.log, "w", encoding="utf-8", errors="replace")
    err_path = args.log + ".err"
    err_fh = open(err_path, "w", encoding="utf-8", errors="replace")
    # NOTE: redirect to files (never -stdout: proven SECURE CRT crash).
    proc = subprocess.Popen(
        cmd, stdout=log_fh, stderr=err_fh, text=True,
        creationflags=0x00000004 | 0x01000000)  # SUSPENDED|BREAKAWAY
    try:
        if not _job._kernel32.AssignProcessToJobObject(
                job.handle, proc._handle):
            raise RuntimeError("AssignProcessToJobObject failed")
    except Exception as exc:
        proc.kill()
        receipt.update({"terminal": "SPAWN_FAILED", "error": str(exc),
                        "end_utc": _ls._utcnow()})
        Path(args.receipt).write_text(json.dumps(receipt, indent=1))
        return 3
    try:
        _job._resume_primary_thread(proc.pid)
    except Exception as exc:
        proc.kill()
        receipt.update({"terminal": "SPAWN_FAILED", "error": str(exc),
                        "end_utc": _ls._utcnow()})
        Path(args.receipt).write_text(json.dumps(receipt, indent=1))
        return 3

    executor = _job.resolve_executor_pid(job, proc.pid, timeout_s=120)
    receipt["launcher_pid"] = proc.pid
    receipt["executor_pid"] = executor.get("executor_pid")
    Path(args.receipt).write_text(json.dumps(receipt, indent=1))

    t0 = time.time()
    rc = None
    while time.time() - t0 < args.timeout_s:
        rc = proc.poll()
        cur = _ls.read_current()
        if cur is not None and cur.run_id == args.run_id:
            _ls.heartbeat(cur)
        if rc is not None:
            break
        time.sleep(min(args.heartbeat_s, 30))
    timed_out = rc is None
    if timed_out:
        try:
            job.terminate_owned(99)
        except Exception:
            pass
        rc = proc.wait(timeout=120)
    drain = _job.wait_for_drain(job, timeout_s=300)
    try:
        log_fh.close()
        err_fh.close()
    except Exception:
        pass
    cls = _ex.classify_exit(int(rc if rc is not None else -1),
                            timed_out=timed_out)
    receipt.update({
        "end_utc": _ls._utcnow(),
        "exit_code_dec": rc,
        "exit_code_hex": hex(int(rc) & 0xFFFFFFFF) if rc is not None else None,
        "termination_class": cls["class"],
        "timed_out": timed_out,
        "drain": drain,
        "log_sha256": sha(args.log),
        "log_bytes": os.path.getsize(args.log)
        if os.path.exists(args.log) else None,
        "job_members_final": job.member_pids(),
    })
    Path(args.receipt).write_text(json.dumps(receipt, indent=1))
    job.close()
    print(json.dumps({"label": args.label, "exit": rc,
                      "class": cls["class"], "drained": drain.get("drained")}))
    return 0 if (rc == 0 and drain.get("drained")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
