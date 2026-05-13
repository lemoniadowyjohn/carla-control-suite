#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ultimate_pipeline.debug.failure_bundle

Writes an always-on forensic bundle when the pipeline hits an exception.

This is designed to be *crash-resilient*:
- It must never raise.
- It must not import carla.
- It creates minimal repro artifacts + fixtures for regression tests.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import traceback
from typing import Any, Dict, Optional

from ultimate_pipeline.debug.carla_crash_fixtures import generate_fixtures


def write_failure_bundle(
    out_dir: str,
    *,
    stage: str,
    xodr_path: Optional[str],
    error: BaseException,
    extra: Optional[Dict[str, Any]] = None,
    run_carla_tests: bool = False,
    carla_timeout_s: float = 180.0,
    carla_retries: int = 1,
    subproc_timeout_s: float = 300.0,
) -> str:
    """Create out_dir/failure_bundle/<ts>/... bundle.

    Returns the bundle directory path.
    """
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_dir = os.path.join(out_dir, "failure_bundle", ts)
    os.makedirs(bundle_dir, exist_ok=True)

    crash_info = {
        "stage": stage,
        "xodr_path": xodr_path,
        "error_type": type(error).__name__,
        "error_str": str(error),
        "traceback": traceback.format_exc(),
        "extra": extra or {},
        "python": sys.version,
        "argv": sys.argv,
    }

    crash_path = os.path.join(bundle_dir, "crash_info.json")
    with open(crash_path, "w", encoding="utf-8") as f:
        json.dump(crash_info, f, indent=2)

    fixture_paths: Dict[str, str] = {}
    if xodr_path and os.path.exists(xodr_path):
        fixtures_dir = os.path.join(bundle_dir, "fixtures")
        fixture_paths = generate_fixtures(xodr_path, fixtures_dir)

    results: Dict[str, Any] = {}
    if run_carla_tests and fixture_paths:
        results_path = os.path.join(bundle_dir, "fixture_results.json")
        for name, fx in fixture_paths.items():
            rep_path = os.path.join(bundle_dir, f"carla_report__{name}.json")
            cmd = [
                sys.executable,
                "-m",
                "ultimate_pipeline.carla_tools.carla_final_test",
                "--xodr",
                fx,
                "--json_out",
                rep_path,
                "--timeout_s",
                str(float(carla_timeout_s)),
                "--retries",
                str(int(carla_retries)),
                "--no_spawn",
            ]
            try:
                r = subprocess.run(cmd, timeout=float(subproc_timeout_s))
                ok = (r.returncode == 0) and os.path.exists(rep_path)
                results[name] = {
                    "fixture": fx,
                    "returncode": r.returncode,
                    "report_path": rep_path if os.path.exists(rep_path) else None,
                    "ok": ok,
                }
            except Exception as e:
                results[name] = {
                    "fixture": fx,
                    "returncode": None,
                    "report_path": None,
                    "ok": False,
                    "error": str(e),
                }
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    return bundle_dir
