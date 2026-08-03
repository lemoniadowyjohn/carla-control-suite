from __future__ import annotations

"""Autopilot availability check (read-only unless --run is used).

- Safe to import without CARLA installed.
- By default, only attempts to connect and prints a minimal status summary.
- With --run, executes a short AutopilotTest and writes a small JSON report.

NOTE: Running --run will spawn actors in CARLA (high-impact). Do NOT run unless you intend to.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import carla  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    carla = None  # type: ignore

from ultimate_pipeline.diagnostics.autopilot_test import AutopilotTest, _require_carla


def carla_status(host: str, port: int, timeout_s: float = 2.0) -> Dict[str, Any]:
    """Lightweight CARLA reachability check (no spawning)."""
    if carla is None:
        return {"ok": False, "reason": "carla_python_api_missing"}

    t0 = time.time()
    try:
        client = carla.Client(host, int(port))  # type: ignore
        client.set_timeout(float(timeout_s))  # type: ignore
        world = client.get_world()  # type: ignore
        m = world.get_map()  # type: ignore
        return {
            "ok": True,
            "host": host,
            "port": int(port),
            "map_name": getattr(m, "name", "unknown"),
            "elapsed_s": round(time.time() - t0, 3),
        }
    except Exception as e:
        return {"ok": False, "host": host, "port": int(port), "error": str(e), "elapsed_s": round(time.time() - t0, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Check CARLA autopilot availability safely.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--out", type=Path, default=None, help="Optional JSON output path")
    ap.add_argument("--run", action="store_true", help="Run the autopilot smoke test (spawns vehicles)")
    ap.add_argument("--vehicles", type=int, default=10)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--logs-dir", type=str, default=None, help="Optional sensor logs dir (only if --run)")

    args = ap.parse_args()

    status = carla_status(args.host, args.port, timeout_s=args.timeout)

    report: Dict[str, Any] = {"status": status, "ran_autopilot_test": False}
    if args.run:
        # High impact: spawns actors. Require explicit CARLA availability.
        _require_carla()
        client = carla.Client(args.host, int(args.port))  # type: ignore
        client.set_timeout(float(args.timeout))  # type: ignore
        ok = AutopilotTest.run(
            client,
            vehicle_count=int(args.vehicles),
            seconds=float(args.seconds),
            enable_recording=bool(args.logs_dir),
            logs_dir=args.logs_dir,
        )
        report["ran_autopilot_test"] = True
        report["autopilot_test_ok"] = bool(ok)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # human output
    if not status.get("ok"):
        print("[autopilot_check] CARLA not reachable / not available:", status)
        return 2
    print("[autopilot_check] CARLA reachable:", status)
    if args.run:
        print("[autopilot_check] autopilot test ran:", report.get("autopilot_test_ok"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
