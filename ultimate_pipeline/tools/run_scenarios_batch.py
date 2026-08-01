#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch ScenarioRunner wrapper (separate step).

Runs run_scenariorunner_once.py per resolved run dir and writes artifacts under:
  <resolved_run_dir>/scenarios/<scenario>/
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ultimate_pipeline.tools.carla_preflight import run_preflight
from ultimate_pipeline.tools import validate_thesis_run


def _expand_runs(tokens: Sequence[str]) -> List[Path]:
    runs: List[Path] = []
    for t in tokens:
        if any(ch in t for ch in ("*", "?")):
            runs.extend([Path(p) for p in sorted(Path(".").glob(t))])
        else:
            runs.append(Path(t))
    return runs


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _resolve_run_dir(p: Path) -> Path:
    try:
        resolved, _meta = validate_thesis_run._resolve_real_run_dir(p)  # type: ignore[attr-defined]
        return resolved
    except Exception:
        return p


def _scenario_name_from_xosc(xosc: Path, override: str | None) -> str:
    if override:
        return str(override)
    return xosc.stem


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="Run dirs (wrapper or resolved). Globs supported.")
    ap.add_argument("--xosc", required=True, type=Path, help="OpenSCENARIO .xosc file")
    ap.add_argument("--scenario-name", default=None)
    ap.add_argument("--host", default=os.getenv("UP_CARLA_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("UP_CARLA_PORT", "2000")))
    ap.add_argument("--timeout-s", type=int, default=int(os.getenv("UP_SCENARIORUNNER_TIMEOUT_S", "900")))
    ap.add_argument("--scenario-runner-root", type=Path, default=None)
    ap.add_argument("--additional-args", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    xosc = args.xosc.resolve()
    if not xosc.is_file():
        raise SystemExit(f"xosc not found: {xosc}")

    scenario_name = _scenario_name_from_xosc(xosc, args.scenario_name)
    runs = _expand_runs(args.runs)
    if not runs:
        raise SystemExit("No runs resolved.")

    for run in runs:
        resolved = _resolve_run_dir(run.resolve())
        out_dir = resolved / "scenarios" / scenario_name
        out_dir.mkdir(parents=True, exist_ok=True)

        lock_path = resolved / "perception.lock"
        if lock_path.exists():
            _write_json(out_dir / "scenariorunner_status.json", {
                "ok": False,
                "reason": "perception_lock_present",
                "run_dir": str(resolved),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
            continue

        preflight = run_preflight(
            host=str(args.host),
            port=int(args.port),
            out_dir=str(out_dir),
            autostart=os.getenv("UP_CARLA_AUTOSTART", "").strip().lower() in ("1", "true", "yes", "on"),
            force_restart=os.getenv("UP_CARLA_FORCE_RESTART", "").strip().lower() in ("1", "true", "yes", "on"),
        )
        if not preflight.get("ok"):
            _write_json(out_dir / "scenariorunner_status.json", {
                "ok": False,
                "reason": "carla_not_ready",
                "carla_reachability": preflight,
                "run_dir": str(resolved),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
            continue

        cmd = [
            sys.executable, "-m", "ultimate_pipeline.tools.run_scenariorunner_once",
            "--xosc", str(xosc),
            "--host", str(args.host),
            "--port", str(int(args.port)),
            "--timeout-s", str(int(args.timeout_s)),
            "--out", str(out_dir),
        ]
        if args.scenario_runner_root:
            cmd += ["--scenario-runner-root", str(args.scenario_runner_root.resolve())]
        if args.additional_args:
            cmd += ["--additional-args", *args.additional_args]

        if args.dry_run:
            _write_json(out_dir / "scenariorunner_status.json", {
                "ok": True,
                "reason": "dry_run",
                "cmd": cmd,
                "run_dir": str(resolved),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
            continue

        subprocess.run(cmd, check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
