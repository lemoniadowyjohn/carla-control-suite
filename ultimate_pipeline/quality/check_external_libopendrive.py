#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Optional external OpenDRIVE validation using libOpenDRIVE.

This module is **safe by default**:
- If no validator binary is configured/found, it returns ok=True with status='skipped'.
- It never imports CARLA.
- It is suitable for CI/HPC.

Expected integration:
- called from ultimate_pipeline.quality.quality_gates when SETTINGS enables it.

Binary contract (you control this):
- Provide a small executable that accepts:
    odr_validate <path_to.xodr> --out <report.json>
- The report.json should be JSON. This wrapper will read it and attach to pipeline artifacts.

If you don't have a validator exe yet, you can keep this gate enabled in "warn" mode
(i.e., not strict) and it will simply record that it was skipped.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _pick_validator_exe(settings_exe: Optional[str]) -> Optional[str]:
    # 1) env override (highest priority)
    env = os.getenv("UP_LIBOPENDRIVE_VALIDATOR_EXE", "").strip()
    if env:
        return env if Path(env).exists() else env  # keep for diagnostics

    # 2) settings value
    if settings_exe:
        return settings_exe if Path(settings_exe).exists() else settings_exe

    # 3) common local dev default (optional)
    # You can build a tiny CLI in external/libOpenDRIVE-main/build/odr_validate(.exe)
    repo_root = Path(__file__).resolve().parents[2]
    cands = [
        repo_root / "external" / "libOpenDRIVE-main" / "build" / "odr_validate.exe",
        repo_root / "external" / "libOpenDRIVE-main" / "build" / "odr_validate",
    ]
    for c in cands:
        if c.exists():
            return str(c)
    return None


def run_external_libopendrive_validation(
    xodr_path: str,
    *,
    out_dir: Optional[str] = None,
    validator_exe: Optional[str] = None,
    strict: bool = False,
    timeout_s: float = 20.0,
) -> Dict[str, Any]:
    """Run external validator if configured.

    Returns a JSON-like dict:
      - ok: bool
      - status: 'pass' | 'fail' | 'skipped' | 'error'
      - details...
    """
    t0 = time.time()
    xodr = Path(xodr_path)

    if not xodr.exists():
        rep = {"ok": False, "status": "error", "reason": "xodr_missing", "path": xodr_path}
        return rep

    exe = _pick_validator_exe(validator_exe)
    if not exe or not Path(exe).exists():
        rep = {
            "ok": True,
            "status": "skipped",
            "reason": "validator_exe_not_found",
            "configured_exe": exe or "",
            "xodr_path": str(xodr),
            "elapsed_s": round(time.time() - t0, 3),
        }
        return rep

    out_path: Optional[Path] = None
    if out_dir:
        out_path = Path(out_dir) / "external_libopendrive_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

    # Define the contract to your CLI
    cmd = [str(exe), str(xodr)]
    if out_path:
        cmd += ["--out", str(out_path)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=float(timeout_s))
        rc = int(proc.returncode)

        rep: Dict[str, Any] = {
            "ok": (rc == 0),
            "status": "pass" if rc == 0 else "fail",
            "returncode": rc,
            "cmd": cmd,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "elapsed_s": round(time.time() - t0, 3),
            "xodr_path": str(xodr),
        }

        if out_path and out_path.exists():
            try:
                rep["report"] = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                rep["report_parse_error"] = True

        # Strict mode converts nonzero returncodes into ok=False
        if strict and rc != 0:
            rep["ok"] = False

        return rep

    except subprocess.TimeoutExpired as e:
        rep = {
            "ok": False if strict else True,
            "status": "error" if strict else "skipped",
            "reason": "validator_timeout",
            "timeout_s": timeout_s,
            "cmd": cmd,
            "elapsed_s": round(time.time() - t0, 3),
        }
        return rep
    except Exception as e:
        rep = {
            "ok": False if strict else True,
            "status": "error" if strict else "skipped",
            "reason": "validator_exception",
            "error": str(e),
            "cmd": cmd,
            "elapsed_s": round(time.time() - t0, 3),
        }
        return rep
