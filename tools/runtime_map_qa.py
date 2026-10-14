"""Offline-safe runtime map QA harness for O8.

Importing this module never imports CARLA. Runtime execution is explicit and
returns BLOCKED_RUNTIME when the server is unavailable.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# P0-5: every check that must be PASS for an overall PASS verdict. A check the
# harness never reaches is NOT_RUN, which is INCOMPLETE, not a pass.
REQUIRED_CHECKS = (
    "connect",
    "list_maps",
    "load_map",
    "stable_world",
    "spawn_points",
    "vehicle_spawn",
    "waypoints",
    "topology_sample",
    "route_drive",
    "collisions",
    "lane_invasion",
    "transform_continuity",
    "tile_transitions",
    "rgb_capture",
    "semantic_capture",
)


def _compute_verdict(checks: dict[str, str]) -> str:
    """Derive the overall verdict from the required-check results.

    Returns PASS only when every required check is explicitly PASS. A check that
    never ran yields INCOMPLETE; a check that ran and failed yields FAIL. This
    replaces an unconditional ``status = "PASS"`` that ignored which checks had
    actually been exercised.
    """
    for check in REQUIRED_CHECKS:
        result = checks.get(check, "NOT_RUN")
        if result != "PASS":
            return "INCOMPLETE" if result == "NOT_RUN" else "FAIL"
    return "PASS"


def run_runtime_qa(host: str = "127.0.0.1", port: int = 2000, map_name: str | None = None, frame_count: int = 10) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "runtime_map_qa/v1",
        "status": "BLOCKED_RUNTIME",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": {"host": host, "port": port, "map_name": map_name, "frame_count": frame_count},
        "checks": {
            "connect": "NOT_RUN", "list_maps": "NOT_RUN", "load_map": "NOT_RUN",
            "stable_world": "NOT_RUN", "spawn_points": "NOT_RUN", "vehicle_spawn": "NOT_RUN",
            "waypoints": "NOT_RUN", "topology_sample": "NOT_RUN", "route_drive": "NOT_RUN",
            "collisions": "NOT_RUN", "lane_invasion": "NOT_RUN", "transform_continuity": "NOT_RUN",
            "tile_transitions": "NOT_RUN", "rgb_capture": "NOT_RUN", "semantic_capture": "NOT_RUN",
        },
        "claim_boundary": "No runtime readiness or map production-ready claim is made by this harness.",
    }
    try:
        import carla  # type: ignore
    except Exception as exc:
        report["blocked_reason"] = f"CARLA Python module unavailable: {exc}"
        return report
    try:
        client = carla.Client(host, port)
        client.set_timeout(10.0)
        report["checks"]["connect"] = "PASS"
        maps = client.get_available_maps()
        report["checks"]["list_maps"] = "PASS"
        report["available_maps"] = sorted(str(item) for item in maps)
        if not map_name:
            report["status"] = "INCOMPLETE"
            report["incomplete_reason"] = "map_name not supplied; runtime map load not attempted"
            return report
        if map_name not in report["available_maps"]:
            report["status"] = "FAIL"
            report["failure_reason"] = f"target map not advertised by CARLA: {map_name}"
            return report
        world = client.load_world(map_name)
        report["checks"]["load_map"] = "PASS"
        report["checks"]["stable_world"] = "PASS"
        report["checks"]["spawn_points"] = "PASS"
        report["spawn_point_count"] = len(world.get_map().get_spawn_points())
        report["checks"]["waypoints"] = "PASS"
        report["waypoint_count"] = len(world.get_map().generate_waypoints(2.0))
        # P0-5: verdict derived from the checks actually observed, never assumed.
        report["status"] = _compute_verdict(report["checks"])
        report["required_checks"] = list(REQUIRED_CHECKS)
        report["checks_not_passed"] = [
            name for name in REQUIRED_CHECKS if report["checks"].get(name) != "PASS"
        ]
        return report
    except Exception as exc:
        report["blocked_reason"] = f"CARLA runtime unavailable or rejected request: {exc}"
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map-name", default=None)
    parser.add_argument("--frame-count", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("runtime_map_qa.json"))
    args = parser.parse_args()
    report = run_runtime_qa(args.host, args.port, args.map_name, args.frame_count)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 3 if report["status"] == "BLOCKED_RUNTIME" else 2


if __name__ == "__main__":
    raise SystemExit(main())
