#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
One-shot smoke runner for thesis repo.
Outputs under artifacts/_smoke_checks/<timestamp>/ with per-step logs + INDEX.json.

Fail-fast steps:
  1) env_check_carla
  2) carla_probe_port
  3) calib_sanity_check
  4) preflight_xodr_loadability

Best-effort steps:
  5) load_final_into_carla (runtime load attempt)
  6) carla_screenshot_once (optional)
  7) run_perception_pair (optional; requires manual town + calib)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _truthy(v: Optional[str]) -> bool:
    if not v:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _have_module(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    _mkdir(path.parent)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=True), encoding="utf-8")


def _run_step(
    *,
    name: str,
    cmd: list[str],
    out_dir: Path,
    env: Dict[str, str],
    fail_fast: bool,
) -> Dict[str, Any]:
    log_path = out_dir / f"{name}.log"
    started = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    proc = None
    rc = 999
    try:
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"[cmd] {' '.join(cmd)}\n")
            f.write(f"[started_utc] {started}\n\n")
            f.flush()
            proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=str(out_dir.parent))
            rc = int(proc.returncode)
    except Exception as exc:
        rc = 998
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n[runner_exception] {exc}\n")

    result = {
        "name": name,
        "cmd": cmd,
        "log": str(log_path),
        "returncode": rc,
        "status": "PASS" if rc == 0 else "FAIL",
        "started_utc": started,
    }
    if fail_fast and rc != 0:
        raise RuntimeError(f"FAIL-FAST step failed: {name} (rc={rc}). See {log_path}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Full smoke runner for CARLA thesis repo.")
    ap.add_argument("--xodr", required=True, help="Path to final .xodr to test (generated map).")
    ap.add_argument(
        "--out-root",
        default="artifacts/_smoke_checks",
        help="Root output dir; timestamp subdir will be created under this.",
    )
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host for probe/screenshot tools.")
    ap.add_argument("--port", default=2000, type=int, help="CARLA port for probe/screenshot tools.")
    ap.add_argument(
        "--calib",
        default=None,
        help="Path to calib_data.json. Required only if --run-perception is set.",
    )
    ap.add_argument(
        "--manual-town",
        choices=["Grid0821", "Grid0828"],
        default="Grid0828",
        help="Manual town for paired perception run (if enabled).",
    )
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--duration", type=float, default=15.0)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--run-perception", action="store_true", help="Run paired perception capture (best-effort).")
    ap.add_argument("--run-screenshot", action="store_true", help="Run screenshot_once (best-effort).")
    args = ap.parse_args()

    xodr = Path(args.xodr).resolve()
    if not xodr.exists() or xodr.suffix.lower() != ".xodr":
        print(f"[ERROR] Invalid --xodr: {xodr}")
        return 2

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path(args.out_root).resolve()
    out_dir = out_root / stamp
    _mkdir(out_dir)

    # Environment (conservative defaults)
    env = dict(os.environ)
    env.setdefault("UP_ALLOW_TILE_QA_FAIL", "1")

    index: Dict[str, Any] = {
        "timestamp_local": stamp,
        "xodr": str(xodr),
        "host": args.host,
        "port": args.port,
        "steps": [],
        "artifacts": {},
        "notes": [],
    }

    # ---- Steps 1–4 (fail-fast) ----
    steps = [_run_step(
        name="01_env_check_carla",
        cmd=[sys.executable, "-m", "ultimate_pipeline.tools.env_check_carla"],
        out_dir=out_dir,
        env=env,
        fail_fast=True,
    ), _run_step(
        name="02_carla_probe_port",
        cmd=[sys.executable, "-m", "ultimate_pipeline.tools.carla_probe_port"],
        out_dir=out_dir,
        env=env,
        fail_fast=True,
    ), _run_step(
        name="03_calib_sanity_check",
        cmd=[sys.executable, "-m", "ultimate_pipeline.tools.calib_sanity_check"],
        out_dir=out_dir,
        env=env,
        fail_fast=True,
    )]

    preflight_out = out_dir / "preflight"
    _mkdir(preflight_out)
    steps.append(
        _run_step(
            name="04_preflight_xodr_loadability",
            cmd=[
                sys.executable,
                "-m",
                "ultimate_pipeline.tools.preflight_xodr_loadability",
                "--xodr",
                str(xodr),
                "--out",
                str(preflight_out),
            ],
            out_dir=out_dir,
            env=env,
            fail_fast=True,
        )
    )
    index["artifacts"]["preflight_report"] = str(preflight_out / "preflight_report.json")

    # ---- Step 5 (best-effort): runtime load attempt ----
    if _have_module("ultimate_pipeline.tools.load_final_into_carla"):
        # NOTE: this tool expects positional xodr path and hardcodes 127.0.0.1:2000 internally.
        steps.append(
            _run_step(
                name="05_load_final_into_carla",
                cmd=[sys.executable, "-m", "ultimate_pipeline.tools.load_final_into_carla", str(xodr)],
                out_dir=out_dir,
                env=env,
                fail_fast=False,
            )
        )
        index["artifacts"]["carla_load_attempt"] = str(out_dir / "05_load_final_into_carla.log")
    else:
        index["notes"].append("SKIP: ultimate_pipeline.tools.load_final_into_carla not found")

    # ---- Step 6 (best-effort): screenshot_once ----
    if args.run_screenshot and _have_module("ultimate_pipeline.tools.carla_screenshot_once"):
        scr_out = out_dir / "screenshot_once"
        _mkdir(scr_out)
        steps.append(
            _run_step(
                name="06_carla_screenshot_once",
                cmd=[
                    sys.executable,
                    "-m",
                    "ultimate_pipeline.tools.carla_screenshot_once",
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--out",
                    str(scr_out),
                ],
                out_dir=out_dir,
                env=env,
                fail_fast=False,
            )
        )
        index["artifacts"]["screenshot_png"] = str(scr_out / "screenshot_once.png")
        index["artifacts"]["screenshot_result"] = str(scr_out / "screenshot_result.json")
    elif args.run_screenshot:
        index["notes"].append("SKIP: ultimate_pipeline.tools.carla_screenshot_once not found")

    # ---- Step 7 (best-effort): paired perception capture ----
    if args.run_perception:
        if not _have_module("ultimate_pipeline.tools.run_perception_pair"):
            index["notes"].append("SKIP: ultimate_pipeline.tools.run_perception_pair not found")
        elif not args.calib:
            index["notes"].append("SKIP: --run-perception set but --calib not provided")
        else:
            calib = Path(args.calib).resolve()
            if not calib.exists():
                index["notes"].append(f"SKIP: calib path does not exist: {calib}")
            else:
                percep_out = out_dir / "perception_pair"
                _mkdir(percep_out)
                steps.append(
                    _run_step(
                        name="07_run_perception_pair",
                        cmd=[
                            sys.executable,
                            "-m",
                            "ultimate_pipeline.tools.run_perception_pair",
                            "--manual-town",
                            args.manual_town,
                            "--xodr-in",
                            str(xodr),
                            "--calib",
                            str(calib),
                            "--out-root",
                            str(percep_out),
                            "--spawn-index",
                            str(args.spawn_index),
                            "--fps",
                            str(args.fps),
                            "--duration",
                            str(args.duration),
                            "--host",
                            args.host,
                            "--port",
                            str(args.port),
                        ],
                        out_dir=out_dir,
                        env=env,
                        fail_fast=False,
                    )
                )
                index["artifacts"]["perception_out_root"] = str(percep_out)

    index["steps"] = steps
    _write_json(out_dir / "INDEX.json", index)

    # Overall status: pass if fail-fast steps passed (they would have raised otherwise).
    print(f"[OK] Smoke run complete: {out_dir}")
    print(f"[OK] INDEX.json: {out_dir / 'INDEX.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
