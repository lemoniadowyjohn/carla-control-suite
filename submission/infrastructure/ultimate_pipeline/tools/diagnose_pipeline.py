#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick diagnostics for the Ultimate Pipeline (offline-safe).

Goal: give you a one-command sanity check that answers:
- Can core modules import?
- Are optional deps available (carla / numpy / pillow / shapely)?
- Are key entrypoints present (run_experiments, perception, batch runner)?
- Where would perception save images?

This does NOT start CARLA. It's a dry import + filesystem probe.

Usage:
  python -m ultimate_pipeline.tools.diagnose_pipeline --out <dir>
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


OPTIONAL_MODULES = [
    "carla",
    "numpy",
    "PIL",
    "cv2",
    "shapely",
]

CORE_IMPORTS = [
    "ultimate_pipeline.tools.run_experiments",
    "ultimate_pipeline.tools.run_thesis_experiments",
    "ultimate_pipeline.tools.run_perception_safe",
    "ultimate_pipeline.tools.tile_qa_batch",
    "ultimate_pipeline.quality.check_lane_link_targets_exist",
    "ultimate_pipeline.config.settings",
]


def _probe_import(name: str) -> Dict[str, Any]:
    try:
        importlib.import_module(name)
        return {"ok": True, "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


def run_diagnostics(out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    report: Dict[str, Any] = {
        "generated_at_utc": now,
        "python": {"executable": sys.executable, "version": sys.version},
        "cwd": str(Path.cwd()),
        "env": {
            "UP_CARLA_EXE": os.getenv("UP_CARLA_EXE", ""),
            "UP_CARLA_HOST": os.getenv("UP_CARLA_HOST", ""),
            "UP_CARLA_PORT": os.getenv("UP_CARLA_PORT", ""),
            "UP_OUTPUT_DIR": os.getenv("UP_OUTPUT_DIR", ""),
        },
        "imports": {},
        "optional_deps": {},
        "notes": [],
    }

    for mod in CORE_IMPORTS:
        report["imports"][mod] = _probe_import(mod)

    for mod in OPTIONAL_MODULES:
        report["optional_deps"][mod] = _probe_import(mod)

    # Basic file probe: calib file exists?
    try:
        from ultimate_pipeline.config.settings import SETTINGS
        calib = Path(getattr(SETTINGS, "SENSOR_CALIB_JSON", ""))
        report["calibration"] = {"path": str(calib), "exists": calib.exists()}
        report["output_dir_default"] = str(Path(SETTINGS.output_dir()).resolve())
    except Exception as exc:  # noqa: BLE001
        report["calibration"] = {"path": "", "exists": False, "error": repr(exc)}

    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True, help="Directory to write diagnostics.json")
    args = ap.parse_args()

    rep = run_diagnostics(args.out)
    out_path = args.out / "diagnostics.json"
    out_path.write_text(json.dumps(rep, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"[diagnose_pipeline] wrote {out_path}")
    # Non-zero only if a *core* import fails
    core_ok = all(v.get("ok") for v in rep.get("imports", {}).values())
    return 0 if core_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
