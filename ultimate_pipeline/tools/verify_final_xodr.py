#!/usr/bin/env python3
"""Offline final-XODR verification for CARLA lane-width readiness.

This command performs static XML checks only. It does not connect to CARLA.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ultimate_pipeline.quality.lane_width_invariants import (
    enforce_lane_width_invariants_on_root,
)


_LANE_TYPES_REQUIRING_WIDTH = (
    "driving",
    "shoulder",
    "sidewalk",
    "border",
    "parking",
    "biking",
    "restricted",
    "none",
)

_EXPLICIT_TARGET_TYPES = {"restricted", "none"}


def _lane_requires_width(lane: ET.Element) -> bool:
    lane_id = lane.get("id")
    if lane_id is None:
        return False
    try:
        if int(lane_id) == 0:
            return False
    except Exception:
        pass
    lane_type = (lane.get("type") or "").strip()
    return (not lane_type) or lane_type in _LANE_TYPES_REQUIRING_WIDTH


def _scan_lane_width_warnings(root: ET.Element, max_examples: int = 25) -> Dict[str, Any]:
    examples: List[Dict[str, str]] = []
    restricted_or_none_road_ids = set()
    count = 0
    for road in root.findall("./road"):
        road_id = str(road.get("id", ""))
        for lane_section in road.findall("./lanes/laneSection"):
            section_s = str(lane_section.get("s", "0"))
            for lane in lane_section.findall(".//lane"):
                if not _lane_requires_width(lane):
                    continue
                if lane.find("./width") is not None:
                    continue
                count += 1
                lane_type = str(lane.get("type", ""))
                if lane_type in _EXPLICIT_TARGET_TYPES:
                    restricted_or_none_road_ids.add(road_id)
                if len(examples) < max_examples:
                    examples.append(
                        {
                            "road_id": road_id,
                            "lane_section_s": section_s,
                            "lane_id": str(lane.get("id", "")),
                            "lane_type": lane_type,
                        }
                    )
    return {
        "missing_width_lane_count": count,
        "restricted_or_none_missing_width_road_ids": sorted(
            restricted_or_none_road_ids,
            key=lambda value: (len(value), value),
        ),
        "examples": examples,
    }


def _count_junctions_and_connectors(root: ET.Element) -> Tuple[int, int]:
    junctions = root.findall("./junction")
    connecting_roads = {
        str(conn.get("connectingRoad") or "").strip()
        for junction in junctions
        for conn in junction.findall("./connection")
        if str(conn.get("connectingRoad") or "").strip()
    }
    if connecting_roads:
        return len(junctions), len(connecting_roads)

    connector_roads = [
        road
        for road in root.findall("./road")
        if str(road.get("junction") or "-1").strip() not in ("", "-1")
    ]
    return len(junctions), len(connector_roads)


def _default_report_path(xodr_path: Path) -> Path:
    return xodr_path.with_name("verify_final_xodr_report.json")


def verify_final_xodr(
    xodr_path: Path, report_path: Path | None = None
) -> Dict[str, Any]:
    xodr_path = Path(xodr_path)
    if report_path is None:
        report_path = _default_report_path(xodr_path)
    else:
        report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    parse_error = None
    root = None
    try:
        root = ET.parse(xodr_path).getroot()
    except Exception as exc:
        parse_error = str(exc)

    if root is None:
        road_count = 0
        lane_width = {
            "missing_width_lane_count": 0,
            "restricted_or_none_missing_width_road_ids": [],
            "examples": [],
        }
        invariant_report = None
        junction_count = 0
        connector_count = 0
    else:
        road_count = len(root.findall("./road"))
        lane_width = _scan_lane_width_warnings(root)
        junction_count, connector_count = _count_junctions_and_connectors(root)

        # Dry-run the production invariant on a copy so verification never mutates the file.
        invariant_report = enforce_lane_width_invariants_on_root(copy.deepcopy(root))

    missing_width_count = int(lane_width.get("missing_width_lane_count", 0))
    ok = bool(parse_error is None and missing_width_count == 0)

    report = {
        "schema": "verify_final_xodr_v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "xodr_path": str(xodr_path),
        "ok": ok,
        "parse_error": parse_error,
        "road_count": road_count,
        "junction_count": junction_count,
        "connector_count": connector_count,
        "lane_width_missing": missing_width_count,
        "lane_width_warnings": lane_width,
        "dry_run_invariant_report": invariant_report,
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    return report


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline final-XODR static lane-width verification."
    )
    parser.add_argument("--xodr", type=Path, required=True, help="Final XODR path")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON report path (default: verify_final_xodr_report.json next to XODR)",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    report = verify_final_xodr(args.xodr, args.out)
    status = "PASS" if report["ok"] else "FAIL"
    lane_width = report["lane_width_warnings"]
    road_ids = lane_width.get("restricted_or_none_missing_width_road_ids", [])

    print(
        "[verify_final_xodr] "
        f"roads={report['road_count']} "
        f"junctions={report['junction_count']} "
        f"connectors={report['connector_count']}"
    )
    print(f"[verify_final_xodr] lane_width_missing={report['lane_width_missing']}")
    if road_ids:
        print(
            "[verify_final_xodr] restricted_or_none_missing_width_road_ids="
            + ",".join(str(road_id) for road_id in road_ids)
        )
    print(f"[verify_final_xodr] report={report['report_path']}")
    print(f"[verify_final_xodr] {status}")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
