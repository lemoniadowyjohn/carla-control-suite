#!/usr/bin/env python3
# ultimate_pipeline/tools/run_scenariorunner_once.py
"""
Run a single ScenarioRunner OpenSCENARIO (.xosc) scenario in a thesis-friendly way.

- Uses external/scenario_runner-master without installing it as a package.
- Runs ScenarioRunner as a subprocess for Windows crash containment.
- Produces an artifact folder containing:
  - scenariorunner_status.json (PASS/FAIL + return code)
  - scenariorunner_stdout.txt / scenariorunner_stderr.txt
  - a copy of the .xosc for provenance

Usage:
  python -m ultimate_pipeline.tools.run_scenariorunner_once \
    --xosc external/scenario_runner-master/srunner/examples/CutIn.xosc \
    --host 127.0.0.1 --port 2000 \
    --out ultimate_pipeline_out/<RUN_ID>/scenarios/CutIn
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

def _write_json(p: Path, obj: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xosc", required=True, type=Path, help="Path to OpenSCENARIO .xosc file")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scenario-runner-root", type=Path, default=None, help="Path to external/scenario_runner-master")
    ap.add_argument("--additional-args", nargs="*", default=[], help="Extra args passed to ScenarioRunner")
    return ap.parse_args()

def main() -> int:
    args = _parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    sr_root = args.scenario_runner_root
    if sr_root is None:
        sr_root = Path(__file__).resolve().parents[2] / "external" / "scenario_runner-master"
    sr_root = sr_root.resolve()

    sr_entry = sr_root / "scenario_runner.py"
    if not sr_entry.is_file():
        raise SystemExit(f"ScenarioRunner not found at: {sr_entry}")

    xosc = args.xosc.resolve()
    if not xosc.is_file():
        raise SystemExit(f"xosc not found: {xosc}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(sr_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    cmd = [
        sys.executable,
        str(sr_entry),
        "--openscenario",
        str(xosc),
        "--host",
        str(args.host),
        "--port",
        str(int(args.port)),
    ] + list(args.additional_args)

    t0 = time.time()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(args.timeout_s),
        env=env,
        cwd=str(sr_root),
    )

    (out / "scenariorunner_stdout.txt").write_text(proc.stdout or "", encoding="utf-8", errors="replace")
    (out / "scenariorunner_stderr.txt").write_text(proc.stderr or "", encoding="utf-8", errors="replace")

    status = {
        "ok": proc.returncode == 0,
        "returncode": int(proc.returncode),
        "elapsed_s": round(time.time() - t0, 3),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cmd": cmd,
        "scenario_runner_root": str(sr_root),
        "xosc": str(xosc),
        "host": args.host,
        "port": int(args.port),
    }
    _write_json(out / "scenariorunner_status.json", status)

    try:
        (out / xosc.name).write_text(xosc.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    except Exception:
        pass

    return 0 if status["ok"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
