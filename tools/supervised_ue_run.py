#!/usr/bin/env python3
"""Supervised governed UE run: job-owned tree + lease heartbeat + receipt.

Detached-friendly: lives for the whole operation, heartbeats ITS OWN lease,
then writes a terminal receipt (exit code, Windows class, times, log SHA,
drain state). Every terminal path transitions the lease out of RUNNING.

Contract V2 changes (see reports/PROCESS_IDENTITY_CONTRACT_V2.json):
  * the harness ACQUIRES its own lease instead of adopting whatever lease
    happens to be current
  * the lease is rebound to the real mutation root (pid + creation time)
    after Job assignment and before the run is treated as running
  * heartbeat validates owner identity and fails closed to STALE
  * no naked PID is ever persisted; executor is non-authoritative

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
        "schema": "supervised_ue_run/v2",
        "label": args.label,
        "run_id": args.run_id,
        "command": cmd,
        "start_utc": _ls._utcnow(),
        "heartbeat": "lease heartbeat every %.0fs" % args.heartbeat_s,
        # Contract V2: every authoritative identity carries role + pid +
        # creation_time. A naked PID is never authoritative.
        "supervisor": {
            "role": "supervisor",
            "pid": os.getpid(),
            "creation_time": _ls.process_creation_time(os.getpid()) or "",
        },
        "job": {
            "job_created": False,
            "assignment_attempted": False,
            "assignment_succeeded": False,
            "assigned_root_pid": None,
            "assigned_root_creation_time": None,
        },
        "mutation_root": None,
        "executor": None,
    }
    Path(args.receipt).write_text(json.dumps(receipt, indent=1))

    # Contract V2 stage 1: acquire an admission lease bound to THIS run.
    # Historical defect: the harness never acquired anything; it adopted
    # whatever lease happened to exist via read_current(), so an unrelated
    # or stale lease became the de facto authority for this run.
    lease = None
    try:
        existing = _ls.read_current()
        if existing is not None and _ls.lease_owner_alive(existing) \
                and existing.run_id != args.run_id:
            receipt.update({"terminal": "LEASE_CONFLICT",
                            "error": "live lease held by another run",
                            "conflict_run_id": existing.run_id,
                            "end_utc": _ls._utcnow()})
            Path(args.receipt).write_text(json.dumps(receipt, indent=1))
            return 4
        if existing is not None and not _ls.lease_owner_alive(existing):
            _ls.reconcile_stale()
        lease = _ls.new_lease(
            operation=args.label,
            mutation_domains=["DOMAIN_UNREAL_CONTENT", "DOMAIN_DDC",
                               "DOMAIN_SAVED_INTERMEDIATE",
                               "DOMAIN_COOK_OUTPUT"],
            fingerprint=_ls.fingerprint_operation({"cmd": cmd}),
            mutex_namespace="Global",
            session_id=args.run_id)
        lease.run_id = args.run_id
        _ls._write_current(lease)
        receipt["lease_run_id"] = lease.run_id
    except Exception as exc:
        receipt.update({"terminal": "LEASE_SETUP_FAILED",
                        "error": str(exc), "end_utc": _ls._utcnow()})
        Path(args.receipt).write_text(json.dumps(receipt, indent=1))
        return 4

    def _finish(term, extra=None):
        """Every terminal path transitions the lease out of RUNNING."""
        info = {"terminal": term, "end_utc": _ls._utcnow()}
        if extra:
            info.update(extra)
        if lease is not None:
            try:
                _ls.release(lease, term)
            except Exception as exc:
                info["lease_release_error"] = str(exc)
        receipt.update(info)
        Path(args.receipt).write_text(json.dumps(receipt, indent=1))

    job = _job.create_job()
    receipt["job"]["job_created"] = True
    log_fh = open(args.log, "w", encoding="utf-8", errors="replace")
    err_path = args.log + ".err"
    err_fh = open(err_path, "w", encoding="utf-8", errors="replace")
    # NOTE: redirect to files (never -stdout: proven SECURE CRT crash).
    proc = subprocess.Popen(
        cmd, stdout=log_fh, stderr=err_fh, text=True,
        creationflags=0x00000004 | 0x01000000)  # SUSPENDED|BREAKAWAY
    receipt["job"]["assignment_attempted"] = True
    try:
        if not _job._kernel32.AssignProcessToJobObject(
                job.handle, proc._handle):
            raise RuntimeError("AssignProcessToJobObject failed")
        receipt["job"]["assignment_succeeded"] = True
    except Exception as exc:
        proc.kill()
        _finish("SPAWN_FAILED", {"error": str(exc)})
        return 3
    # Contract V2: the mutation root is the spawned process; record its
    # identity (pid + creation time) as soon as it exists.
    root_ct = _ls.process_creation_time(proc.pid) or ""
    receipt["job"]["assigned_root_pid"] = proc.pid
    receipt["job"]["assigned_root_creation_time"] = root_ct
    receipt["mutation_root"] = {
        "role": "mutation_root",
        "pid": proc.pid,
        "creation_time": root_ct,
    }
    receipt["launcher"] = {
        "role": "launcher",
        "pid": proc.pid,
        "creation_time": root_ct,
    }
    try:
        _ls.rebind_mutation_root(lease, proc.pid)
        _ls._write_current(lease)
    except Exception as exc:
        proc.kill()
        _finish("LEASE_BIND_FAILED", {"error": str(exc)})
        return 4
    try:
        _job._resume_primary_thread(proc.pid)
    except Exception as exc:
        proc.kill()
        _finish("SPAWN_FAILED", {"error": str(exc)})
        return 3

    executor = _job.resolve_executor_pid(job, proc.pid, timeout_s=120)
    ex_pid = executor.get("executor_pid")
    # Contract V2: an executor is non-authoritative. Persist it only with its
    # creation time and an explicit role, or omit it. Never a naked PID.
    if ex_pid:
        receipt["executor"] = {
            "role": "executor",
            "authoritative": False,
            "pid": ex_pid,
            "creation_time": _ls.process_creation_time(ex_pid) or "",
        }
    Path(args.receipt).write_text(json.dumps(receipt, indent=1))

    t0 = time.time()
    rc = None
    owner_lost = None
    while time.time() - t0 < args.timeout_s:
        rc = proc.poll()
        # Heartbeat OUR OWN lease, not whatever happens to be current. The
        # mutation-root identity was bound after Job assignment, so a dead
        # or PID-reused owner now fails closed to STALE.
        _ls.heartbeat(lease)
        if lease.state == "STALE" and owner_lost is None:
            owner_lost = ("lease owner identity lost; heartbeat failed "
                          "closed. Refusing to keep this run represented as "
                          "validly covered.")
            # Stop the mutation immediately rather than continue without
            # exclusive-ownership evidence.
            try:
                job.terminate_owned(98)
            except Exception:
                pass
            break
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
    # The mutation root must be re-verified at terminal: if its PID is gone
    # but was reused, the receipt must not claim identity it cannot prove.
    _finish("TIMED_OUT" if timed_out else cls["class"], {
        "exit_code_dec": rc,
        "exit_code_hex": hex(int(rc) & 0xFFFFFFFF) if rc is not None else None,
        "termination_class": cls["class"],
        "timed_out": timed_out,
        "drain": drain,
        "log_sha256": sha(args.log),
        "log_bytes": os.path.getsize(args.log)
        if os.path.exists(args.log) else None,
        "job_members_final": job.member_pids(),
        "owner_lost": owner_lost,
        "mutation_root_alive_at_terminal":
            bool(lease.state != "STALE"),
        "job_assignment_evidenced_at_runtime": False,
        "job_authority_note":
            "job_created/assignment_succeeded are codepath evidence only; "
            "runtime membership was not independently observed, so it is "
            "never asserted here",
    })
    job.close()
    print(json.dumps({"label": args.label, "exit": rc,
                      "class": cls["class"], "drained": drain.get("drained"),
                      "lease_terminal": lease.terminal_state,
                      "owner_lost": bool(owner_lost)}))
    return 0 if (rc == 0 and drain.get("drained") and not owner_lost) else 1


if __name__ == "__main__":
    raise SystemExit(main())
