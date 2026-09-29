"""Machine-check RQ3 manual/automatic capture contract parity without starting capture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_SHARED = ["carla_server_version", "sensor_rig", "sensor_transforms", "camera_intrinsics", "lidar_parameters", "weather", "synchronous_mode", "fixed_delta", "seed", "route_definition", "class_map", "frame_count", "warm_up", "exclusion_policy"]


def preflight(manual: dict[str, Any], automatic: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for field in ("expected_map_identity", "expected_map_hash", "expected_map_version", "available_in_runtime"):
        if field not in manual:
            failures.append(f"manual missing {field}")
        if field not in automatic:
            failures.append(f"automatic missing {field}")
    for field in REQUIRED_SHARED:
        if field not in shared:
            failures.append(f"shared missing {field}")
    mismatches = []
    if manual.get("available_in_runtime") is not True or automatic.get("available_in_runtime") is not True:
        mismatches.append("both worlds must be available in runtime")
    for field in REQUIRED_SHARED:
        if field in manual and field in automatic and manual[field] != automatic[field]:
            mismatches.append(f"manual/automatic mismatch: {field}")
    for field in ("expected_map_identity", "expected_map_hash", "expected_map_version"):
        if field in manual and field in automatic and manual[field] == automatic[field] and field == "expected_map_identity":
            mismatches.append("manual and automatic expected_map_identity must be distinct worlds")
    status = "PASS" if not failures and not mismatches else "FAIL" if failures or mismatches else "INCOMPLETE"
    return {"schema": "rq3_pairing_preflight/v1", "status": status, "claim": "RQ3_PREFLIGHT_PASS" if status == "PASS" else "RQ3_PREFLIGHT_BLOCKED", "failures": failures, "mismatches": mismatches, "capture_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--automatic", type=Path, required=True)
    parser.add_argument("--shared", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("RQ3_PREFLIGHT.json"))
    args = parser.parse_args()
    try:
        report = preflight(json.loads(args.manual.read_text(encoding="utf-8")), json.loads(args.automatic.read_text(encoding="utf-8")), json.loads(args.shared.read_text(encoding="utf-8")))
    except Exception as exc:
        report = {"schema": "rq3_pairing_preflight/v1", "status": "BLOCKED", "claim": "RQ3_PREFLIGHT_BLOCKED", "failures": [str(exc)], "capture_started": False}
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
