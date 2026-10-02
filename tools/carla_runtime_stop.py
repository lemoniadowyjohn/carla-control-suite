#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop only the CARLA process this wave owns.

Refuses to act unless the PID was recorded in a launch report produced by
tools/carla_runtime_launch.py, so an unrelated CARLA instance can never be
killed. No global taskkill, no name-wide Stop-Process.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

LOG_DIR = Path("reports/carla_runtime")


def owned_pids() -> List[Dict[str, Any]]:
    owned: List[Dict[str, Any]] = []
    if not LOG_DIR.is_dir():
        return owned
    for rep in sorted(LOG_DIR.glob("*_REPORT.json")):
        try:
            d = json.loads(rep.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = d.get("owned_pid")
        if isinstance(pid, int):
            owned.append({"pid": pid, "run_id": d.get("run_id"), "report": str(rep)})
    return owned


def alive(pid: int) -> bool:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue) -ne $null"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return bool((r.stdout or "").strip().lower() == "true")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    owned = owned_pids()
    print(json.dumps({"owned_pids_from_reports": owned}, indent=2))
    if not owned:
        print("no owned CARLA PID recorded; refusing to stop anything")
        return 0

    for rec in owned:
        pid = rec["pid"]
        if not alive(pid):
            print(f"PID {pid} ({rec['run_id']}) not running; nothing to do")
            continue
        if args.dry_run:
            print(f"would stop PID {pid} ({rec['run_id']})")
            continue
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        print(f"stopped owned PID {pid} ({rec['run_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())