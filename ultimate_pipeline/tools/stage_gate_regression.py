#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any, Dict, List

STAGE_PREFIXES = ["01_sanitized","02_sumo_fixed","03_topology","04_elevation","05_planview","06_continuity","07_lanes","08_final"]

def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

def _find_stage_xodr(run_dir: Path, prefix: str) -> Path | None:
    cands = sorted(run_dir.glob(f"{prefix}*.xodr"))
    return cands[0] if cands else None

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    from ultimate_pipeline.run_quality_gates import run_quality_gates

    run_dir = args.run_dir.resolve()
    stages: List[Dict[str, Any]] = []
    for prefix in STAGE_PREFIXES:
        xodr = _find_stage_xodr(run_dir, prefix)
        if xodr is None:
            stages.append({"stage": prefix, "xodr": None, "skipped": True})
            continue
        failures = run_quality_gates(str(xodr)) or {}
        stages.append({"stage": prefix, "xodr": str(xodr), "failures": failures})

    _write_json(args.out, {"run_dir": str(run_dir), "stages": stages})
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
