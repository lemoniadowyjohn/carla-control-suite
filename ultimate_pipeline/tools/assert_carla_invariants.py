#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assert CARLA loadability invariants on an OpenDRIVE file.

This script performs offline validation to ensure an XODR file is safe to load
in CARLA 0.9.16 without triggering MapBuilder crashes.

Invariants checked:
1. No laneSection has s < 0
2. Every laneSection has center lane id=0
3. No dangling lane successor/predecessor references

Usage:
    python -m ultimate_pipeline.tools.assert_carla_invariants --xodr path/to/map.xodr
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class InvariantViolation:
    code: str
    road_id: str
    message: str
    context: Dict[str, Any]


def _safe_float(v: Optional[str], default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Optional[str], default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def check_invariants(xodr_path: str) -> Dict[str, Any]:
    """Check CARLA loadability invariants on an XODR file.

    Returns a dict with:
    - ok: bool (True if all invariants pass)
    - violations: list of violation dicts
    - summary: dict with counts per invariant type
    """
    violations: List[InvariantViolation] = []

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        return {
            "ok": False,
            "violations": [{"code": "parse_error", "message": str(e)}],
            "summary": {"parse_error": 1},
        }

    # Build lane index for successor validation
    # road_id -> list of laneSections, each with set of lane ids
    road_sections: Dict[str, List[Set[int]]] = {}

    for road in root.findall(".//road"):
        rid = road.get("id", "UNKNOWN")
        sections: List[Set[int]] = []

        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            violations.append(InvariantViolation(
                code="missing_lanes",
                road_id=rid,
                message="Road has no <lanes> element",
                context={},
            ))
            continue

        road_length = _safe_float(road.get("length"), -1.0)

        for idx, ls in enumerate(lanes_elem.findall("./laneSection")):
            ls_s = _safe_float(ls.get("s"), -1.0)
            lane_ids: Set[int] = set()

            # --- Invariant 1: No negative s ---
            if ls_s < 0.0:
                violations.append(InvariantViolation(
                    code="negative_s",
                    road_id=rid,
                    message=f"laneSection[{idx}] has negative s={ls_s}",
                    context={"laneSection_index": idx, "s": ls_s},
                ))

            # Check s is within road length
            if road_length > 0 and ls_s > road_length + 1e-3:
                violations.append(InvariantViolation(
                    code="s_exceeds_length",
                    road_id=rid,
                    message=f"laneSection[{idx}] s={ls_s} exceeds road length={road_length}",
                    context={"laneSection_index": idx, "s": ls_s, "road_length": road_length},
                ))

            # --- Invariant 2: Center lane id=0 must exist ---
            center = ls.find("center")
            if center is None:
                violations.append(InvariantViolation(
                    code="missing_center",
                    road_id=rid,
                    message=f"laneSection[{idx}] has no <center> element",
                    context={"laneSection_index": idx},
                ))
            else:
                center_lane = center.find("lane[@id='0']")
                if center_lane is None:
                    violations.append(InvariantViolation(
                        code="missing_center_lane_0",
                        road_id=rid,
                        message=f"laneSection[{idx}] center has no lane id=0",
                        context={"laneSection_index": idx},
                    ))
                else:
                    # Center lane should not be driving
                    if center_lane.get("type") == "driving":
                        violations.append(InvariantViolation(
                            code="center_lane_driving",
                            road_id=rid,
                            message=f"laneSection[{idx}] center lane id=0 has type=driving (should be none)",
                            context={"laneSection_index": idx},
                        ))

            # Collect lane ids for successor validation
            for lane in ls.findall(".//lane"):
                lid = _safe_int(lane.get("id"), None)
                if lid is not None:
                    lane_ids.add(lid)

            sections.append(lane_ids)

        road_sections[rid] = sections

    # --- Invariant 3: No dangling lane successor/predecessor references ---
    for road in root.findall(".//road"):
        rid = road.get("id", "UNKNOWN")
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue

        sections = lanes_elem.findall("./laneSection")
        lane_id_sets = road_sections.get(rid, [])

        for i, ls in enumerate(sections):
            next_set = lane_id_sets[i + 1] if i + 1 < len(lane_id_sets) else None
            prev_set = lane_id_sets[i - 1] if i - 1 >= 0 else None

            for lane in ls.findall(".//lane"):
                lane_id = _safe_int(lane.get("id"), 0)
                link = lane.find("./link")
                if link is None:
                    continue

                succ = link.find("./successor")
                if succ is not None and next_set is not None:
                    tgt = _safe_int(succ.get("id"), 0)
                    if tgt not in next_set:
                        violations.append(InvariantViolation(
                            code="dangling_successor",
                            road_id=rid,
                            message=f"Lane {lane_id} in laneSection[{i}] has successor={tgt} not in next section",
                            context={
                                "laneSection_index": i,
                                "lane_id": lane_id,
                                "target_lane_id": tgt,
                                "available_ids": sorted(next_set),
                            },
                        ))

                pred = link.find("./predecessor")
                if pred is not None and prev_set is not None:
                    tgt = _safe_int(pred.get("id"), 0)
                    if tgt not in prev_set:
                        violations.append(InvariantViolation(
                            code="dangling_predecessor",
                            road_id=rid,
                            message=f"Lane {lane_id} in laneSection[{i}] has predecessor={tgt} not in prev section",
                            context={
                                "laneSection_index": i,
                                "lane_id": lane_id,
                                "target_lane_id": tgt,
                                "available_ids": sorted(prev_set),
                            },
                        ))

    # Build summary
    summary: Dict[str, int] = {}
    for v in violations:
        summary[v.code] = summary.get(v.code, 0) + 1

    return {
        "ok": len(violations) == 0,
        "total_violations": len(violations),
        "violations": [
            {
                "code": v.code,
                "road_id": v.road_id,
                "message": v.message,
                "context": v.context,
            }
            for v in violations
        ],
        "summary": summary,
        "xodr_path": xodr_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert CARLA loadability invariants on an OpenDRIVE file"
    )
    parser.add_argument("--xodr", required=True, help="Path to the XODR file")
    parser.add_argument("--out", help="Output JSON path (optional)")
    parser.add_argument("--strict", action="store_true", help="Exit with error code if any violations")
    args = parser.parse_args()

    result = check_invariants(args.xodr)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote: {args.out}")

    # Print summary
    print("\n=== CARLA Invariant Check ===")
    print(f"File: {args.xodr}")
    print(f"Status: {'PASS' if result['ok'] else 'FAIL'}")
    print(f"Total violations: {result['total_violations']}")

    if result["summary"]:
        print("\nViolation summary:")
        for code, count in sorted(result["summary"].items()):
            print(f"  - {code}: {count}")

    if not result["ok"] and result["violations"]:
        print("\nFirst 10 violations:")
        for v in result["violations"][:10]:
            print(f"  [{v['code']}] road={v['road_id']}: {v['message']}")

    if args.strict and not result["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
