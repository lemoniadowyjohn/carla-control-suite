#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Run CARLA tile validation for a single XODR in an isolated process.

Why this exists:
CARLA's Python API is a C++ extension. Certain failures during map import can
hard-crash the Python interpreter (e.g. Windows exit code 0xC0000409), which
cannot be caught with try/except. Running tile validation in a subprocess lets
the main pipeline survive and record which tile caused the crash.

This tool writes a JSON report to --out on success and exits with code 0.
If the interpreter crashes, the parent process will observe a non-zero return
code or missing report file and can mark the tile as failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict


def _configure_console_encoding() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    _configure_console_encoding()

    p = argparse.ArgumentParser()
    p.add_argument("--xodr", required=True, help="Path to tile .xodr")
    p.add_argument("--out", required=True, help="Path to JSON report to write")
    p.add_argument("--host", default=os.getenv("UP_CARLA_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("UP_CARLA_PORT", "2000")))
    p.add_argument("--timeout", type=float, default=float(os.getenv("UP_CARLA_TIMEOUT_S", "60")))
    args = p.parse_args()

    from ultimate_pipeline.carla_tools.carla_final_check import CarlaFinalTest

    report: Dict[str, Any] = {
        "tool": "tile_validate_one",
        "xodr": args.xodr,
        "host": args.host,
        "port": args.port,
        "started_at_unix": time.time(),
        "status": "unknown",
    }

    try:
        r = CarlaFinalTest.run(args.xodr, host=args.host, port=args.port, timeout=args.timeout)
        # CarlaFinalTest.run returns a dict; embed it to keep backwards compatibility.
        report["carla_final_test"] = r
        report["status"] = "ok" if r.get("map_loaded") else (r.get("spawn_reason") or "fail")
    except Exception as e:
        report["status"] = "exception"
        report["exception"] = str(e)

    report["finished_at_unix"] = time.time()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
