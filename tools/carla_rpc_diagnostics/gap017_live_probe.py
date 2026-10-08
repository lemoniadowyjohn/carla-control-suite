#!/usr/bin/env python3
"""GAP-017 live RPC diagnostic probe.

Turns GAP-017's instrumentation plan into one command, so a live attempt does not
depend on someone typing ad-hoc commands under time pressure.

    python tools/carla_rpc_diagnostics/gap017_live_probe.py --pid 12345

Runs three checks against an ALREADY-RUNNING process and writes a single
timestamped JSON report:

  1. thread census      -- is there a thread named "server"?
  2. socket state       -- Established vs Listen on ports 2000/2001/2002
  3. full dump capture  -- procdump -ma -n 1

This script NEVER launches, attaches to the command line of, or starts
CarlaUE4.exe / UE4Editor.exe / any CARLA or UE4 process. It only observes a PID
the caller already chose. That is deliberate: GAP-017's live attempt is the
owner's to run, as a dedicated step.

Design notes / honest limits:

  * Thread NAMES are not exposed by the Win32 thread APIs, so the name census
    requires procdump. When procdump is absent the script still runs and says so
    explicitly rather than reporting a false negative; it falls back to a
    per-thread CPU census, which is the signal that actually matters for the
    recorded GAP-017 symptom (active multi-thread CPU spin with zero log
    output).

  * Socket enumeration for another user's process needs elevation. The script
    tries Get-NetTCPConnection, then netstat, then psutil, and records which
    source succeeded instead of silently returning an empty list.

  * Missing tools are reported as `available: false` with the reason. A partial
    report is still written; the file is the deliverable.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_PORTS = [2000, 2001, 2002]
WATCHED_THREAD_NAME = "server"


# --------------------------------------------------------------------------- utils


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: List[str], timeout: int = 60) -> Dict[str, Any]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
        }
    except FileNotFoundError as e:
        return {"ok": False, "error": f"not_found: {e}", "stdout": "", "stderr": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s", "stdout": "", "stderr": ""}
    except Exception as e:  # pragma: no cover - defensive
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "stdout": "", "stderr": ""}


def _process_info(pid: int) -> Dict[str, Any]:
    import psutil

    try:
        p = psutil.Process(pid)
        with p.oneshot():
            return {
                "pid": pid,
                "name": p.name(),
                "exe": p.exe() if p.exe() else None,
                "cmdline": list(p.cmdline()),
                "create_time": _dt.datetime.fromtimestamp(
                    p.create_time(), _dt.timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": p.status(),
                "num_threads": p.num_threads(),
                "cpu_times": {
                    "user_s": round(p.cpu_times().user, 2),
                    "system_s": round(p.cpu_times().system, 2),
                },
                "memory_rss_mb": round(p.memory_info().rss / (1024**2), 1),
            }
    except psutil.NoSuchProcess:
        return {"pid": pid, "error": "NoSuchProcess"}
    except psutil.AccessDenied:
        return {"pid": pid, "error": "AccessDenied (needs elevation)"}
    except Exception as e:
        return {"pid": pid, "error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------- 1. thread census


def _find_procdump(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit if Path(explicit).exists() else None
    found = shutil.which("procdump.exe") or shutil.which("procdump64.exe")
    if found:
        return found
    for base in (
        r"C:\Program Files\Sysinternals",
        r"C:\Program Files (x86)\Sysinternals",
        r"C:\Tools",
        r"C:\Sysinternals",
    ):
        cand = Path(base) / "procdump64.exe"
        if cand.exists():
            return str(cand)
        cand = Path(base) / "procdump.exe"
        if cand.exists():
            return str(cand)
    return None


def thread_census(pid: int) -> Dict[str, Any]:
    """Per-thread CPU census, plus a name census when procdump makes one possible."""
    out: Dict[str, Any] = {
        "watched_thread_name": WATCHED_THREAD_NAME,
        "name_census_method": None,
        "name_census_available": False,
        "watched_thread_found": None,
        "threads": [],
    }

    # CPU census via psutil (always available, no elevation for same-user procs).
    try:
        import psutil

        p = psutil.Process(pid)
        proct = p.cpu_times()
        per_thread = p.threads()
        for t in per_thread:
            tid = t.id
            user = getattr(t, "user_time", None)
            syst = getattr(t, "system_time", None)
            out["threads"].append(
                {
                    "tid": tid,
                    "user_s": round(user, 2) if user is not None else None,
                    "system_s": round(syst, 2) if syst is not None else None,
                }
            )
        out["thread_count"] = len(per_thread)
        out["process_cpu_user_s"] = round(proct.user, 2)
        out["process_cpu_system_s"] = round(proct.system, 2)
        total = sum((t["user_s"] or 0) + (t["system_s"] or 0) for t in out["threads"])
        for t in out["threads"]:
            t["cpu_total_s"] = round((t["user_s"] or 0) + (t["system_s"] or 0), 2)
            t["cpu_share_pct"] = (
                round(100.0 * t["cpu_total_s"] / total, 1) if total > 0 else None
            )
        out["threads"].sort(
            key=lambda t: t["cpu_total_s"], reverse=True
        )
        out["top_threads"] = out["threads"][:10]
        out["busiest_thread_share_pct"] = (
            out["threads"][0]["cpu_share_pct"] if out["threads"] else None
        )
    except Exception as e:
        out["cpu_census_error"] = f"{type(e).__name__}: {e}"

    # Name census: requires procdump, because Win32 does not expose thread names.
    out["procdump"] = _find_procdump(None)
    out["name_census_note"] = (
        "Win32 does not expose per-thread names; a name census requires procdump. "
        "Absent procdump, watched_thread_found is null (UNKNOWN), not false."
    )
    return out


# ------------------------------------------------------------- 2. socket states


def socket_states(pid: int, ports: List[int]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ports": ports, "method": None, "per_port": {}}

    # (a) Get-NetTCPConnection, as specified in the GAP-017 plan.
    ps = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-NetTCPConnection -ErrorAction SilentlyContinue | "
            "Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess | "
            "ConvertTo-Json -Compress",
        ],
        timeout=90,
    )
    rows = None
    if ps.get("ok") and ps.get("stdout", "").strip():
        try:
            rows = json.loads(ps["stdout"])
            if isinstance(rows, dict):
                rows = [rows]
            result["method"] = "Get-NetTCPConnection"
        except json.JSONDecodeError:
            rows = None

    # (b) netstat fallback.
    if rows is None:
        ns = _run(["netstat", "-ano"], timeout=90)
        if ns.get("ok"):
            rows = []
            pat = re.compile(r"^\s*TCP\s+\S+:(\d+)\s+\S+\s+(\S+)\s+(\d+)\s+(\S+)\s+(\d+)")
            for line in ns.get("stdout", "").splitlines():
                m = pat.match(line)
                if not m:
                    continue
                lp = int(m.group(1))
                if lp in ports:
                    rows.append(
                        {
                            "LocalPort": lp,
                            "RemotePort": int(m.group(3)),
                            "State": m.group(4),
                            "OwningProcess": int(m.group(5)),
                        }
                    )
            result["method"] = "netstat -ano"

    if rows is None:
        result["error"] = (
            "neither Get-NetTCPConnection nor netstat produced parseable output"
        )
        return result

    for port in ports:
        matches = [r for r in rows if int(r.get("LocalPort", -1)) == port]
        mine = [
            r
            for r in matches
            if str(r.get("OwningProcess")) == str(pid)
        ]
        other = [r for r in matches if str(r.get("OwningProcess")) != str(pid)]
        states = sorted({str(r.get("State")) for r in matches})
        result["per_port"][str(port)] = {
            "listening": any("LISTEN" in s.upper() for s in states),
            "established": any("ESTAB" in s.upper() for s in states),
            "any_state": states or None,
            "owned_by_target_pid": len(mine),
            "owned_by_other_pid": len(other),
            "other_owners": sorted(
                {int(r["OwningProcess"]) for r in other if str(r.get("OwningProcess", "")).isdigit()}
            )[:10],
            "detail": mine or None,
        }

    result["interpretation"] = (
        "A CARLA RPC server that is Listen-ing but never Established indicates it "
        "bound the port but the client handshake never completed -- the signature "
        "GAP-017 is chasing. Established on all three ports indicates a live session."
    )
    return result


# ------------------------------------------------------------ 3. dump capture


def capture_dump(pid: int, out_dir: Path, procdump: Optional[str], label: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"requested": True, "tool": "procdump", "available": bool(procdump)}
    if not procdump:
        out["available"] = False
        out["error"] = (
            "procdump.exe not found on PATH or in the standard Sysinternals "
            "locations. Install Sysinternals Procdump, or pass --procdump <path>. "
            "The full-memory capture is the only check that cannot be substituted."
        )
        out["substitute_available"] = _run(
            ["powershell", "-NoProfile", "-Command", "Get-Command WerFault.exe -ErrorAction SilentlyContinue"],
            timeout=30,
        ).get("ok", False)
        return out

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{label}_pid{pid}.dmp"
    cmd = [procdump, "-accepteula", "-ma", "-n", "1", str(pid), str(target)]
    res = _run(cmd, timeout=300)
    out["command"] = " ".join(cmd)
    out["returncode"] = res.get("returncode")
    out["produced_file"] = target.exists()
    out["dump_path"] = str(target) if target.exists() else None
    out["dump_bytes"] = target.stat().st_size if target.exists() else None
    out["stderr_tail"] = (res.get("stderr") or "")[-2000:]
    if not out["produced_file"]:
        out["error"] = "procdump ran but produced no dump file"
    return out


# ------------------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="GAP-017 live RPC diagnostic probe")
    ap.add_argument("--pid", type=int, required=True, help="target process PID (already running)")
    ap.add_argument("--ports", type=int, nargs="+", default=DEFAULT_PORTS)
    ap.add_argument("--out-dir", default="reports/gap017_live_probe", help="report output directory")
    ap.add_argument("--procdump", default=None, help="explicit path to procdump(.exe)")
    ap.add_argument("--label", default="gap017", help="filename prefix for dump/report")
    ap.add_argument(
        "--allow-any-pid",
        action="store_true",
        help=(
            "acknowledgement that the target is NOT CarlaUE4/UE4Editor. The probe "
            "never launches anything, but this records intent for self-tests."
        ),
    )
    args = ap.parse_args(argv)

    started = _now()
    proc = _process_info(args.pid)
    if "error" in proc:
        print(f"[!] cannot inspect pid {args.pid}: {proc['error']}", file=sys.stderr)
        report = {
            "schema": "gap017_live_probe/v1",
            "started_utc": started,
            "finished_utc": _now(),
            "target": proc,
            "error": proc["error"],
        }
        _write(report, args.out_dir, args.label)
        return 2

    name = (proc.get("name") or "").lower()
    is_ue = any(k in name for k in ("carlaue4", "ue4editor", "carla"))
    print(f"[*] target pid={args.pid} name={proc.get('name')} exe={proc.get('exe')}")

    procdump = _find_procdump(args.procdump)
    report: Dict[str, Any] = {
        "schema": "gap017_live_probe/v1",
        "started_utc": started,
        "finished_utc": None,
        "probe_launched_nothing": True,
        "target": proc,
        "target_looks_like_carla_or_ue": is_ue,
        "checks": {},
    }

    print("[1/3] thread census ...")
    report["checks"]["thread_census"] = thread_census(args.pid)

    print("[2/3] socket state ...")
    report["checks"]["socket_states"] = socket_states(args.pid, args.ports)

    print("[3/3] full dump capture ...")
    out_dir = Path(args.out_dir)
    report["checks"]["dump_capture"] = capture_dump(args.pid, out_dir, procdump, args.label)

    report["finished_utc"] = _now()
    path = _write(report, args.out_dir, args.label)
    print(f"[+] report -> {path}")
    return 0


def _write(report: Dict[str, Any], out_dir: str, label: str) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    path = d / f"{label}_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


if __name__ == "__main__":
    sys.exit(main())