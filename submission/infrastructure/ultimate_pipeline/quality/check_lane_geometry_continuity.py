# ultimate_pipeline/quality/check_lane_geometry_continuity.py
# -*- coding: utf-8 -*-

"""
Lane geometry continuity check.

Detects discontinuities in laneOffset and lane width functions at laneSection boundaries.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except Exception:
        return default


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _eval_poly(a: float, b: float, c: float, d: float, ds: float) -> float:
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _lane_offset_elements(road: ET.Element) -> List[ET.Element]:
    offsets = road.findall("lanes/laneOffset")
    return sorted(offsets, key=lambda el: _safe_float(el.get("s"), 0.0))


def _lane_offset_at(road: ET.Element, s_abs: float) -> Optional[float]:
    offsets = _lane_offset_elements(road)
    if not offsets:
        return 0.0
    chosen = offsets[0]
    for el in offsets:
        if _safe_float(el.get("s"), 0.0) <= s_abs:
            chosen = el
        else:
            break
    s0 = _safe_float(chosen.get("s"), 0.0)
    a = _safe_float(chosen.get("a"), 0.0)
    b = _safe_float(chosen.get("b"), 0.0)
    c = _safe_float(chosen.get("c"), 0.0)
    d = _safe_float(chosen.get("d"), 0.0)
    return _eval_poly(a, b, c, d, max(0.0, s_abs - s0))


def _lane_width_at(lane: ET.Element, s_rel: float) -> Optional[float]:
    widths = lane.findall("width")
    if not widths:
        return None
    widths = sorted(widths, key=lambda el: _safe_float(el.get("sOffset"), 0.0))
    chosen = widths[0]
    for el in widths:
        if _safe_float(el.get("sOffset"), 0.0) <= s_rel:
            chosen = el
        else:
            break
    s0 = _safe_float(chosen.get("sOffset"), 0.0)
    a = _safe_float(chosen.get("a"), 0.0)
    b = _safe_float(chosen.get("b"), 0.0)
    c = _safe_float(chosen.get("c"), 0.0)
    d = _safe_float(chosen.get("d"), 0.0)
    return _eval_poly(a, b, c, d, max(0.0, s_rel - s0))


def _collect_lanes(section: ET.Element) -> Dict[str, ET.Element]:
    lanes: Dict[str, ET.Element] = {}
    for side in ("left", "center", "right"):
        side_el = section.find(side)
        if side_el is None:
            continue
        for lane in side_el.findall("lane"):
            lane_id = lane.get("id")
            if lane_id is not None:
                lanes[str(lane_id)] = lane
    return lanes


def check_lane_geometry_continuity(
    xodr_path: str,
    *,
    lane_offset_eps: Optional[float] = None,
    lane_width_eps: Optional[float] = None,
) -> Dict[str, Any]:
    lane_offset_eps = float(lane_offset_eps if lane_offset_eps is not None else _env_float("UP_LANE_OFFSET_CONT_EPS", 0.05))
    lane_width_eps = float(lane_width_eps if lane_width_eps is not None else _env_float("UP_LANE_WIDTH_CONT_EPS", 0.10))
    eps_s = 1e-3

    report: Dict[str, Any] = {
        "ok": True,
        "n_issues": 0,
        "issues": [],
        "tolerances": {
            "lane_offset_eps": lane_offset_eps,
            "lane_width_eps": lane_width_eps,
        },
        "xodr_path": xodr_path,
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as exc:
        report["ok"] = False
        report["issues"] = [{"type": "parse_error", "error": str(exc)}]
        report["n_issues"] = len(report["issues"])
        return report

    for road in root.findall("road"):
        road_id = road.get("id", "")
        lane_sections = road.findall("lanes/laneSection")
        if len(lane_sections) < 2:
            continue
        lane_sections = sorted(lane_sections, key=lambda el: _safe_float(el.get("s"), 0.0))

        for idx in range(len(lane_sections) - 1):
            prev_sec = lane_sections[idx]
            next_sec = lane_sections[idx + 1]
            s_prev = _safe_float(prev_sec.get("s"), 0.0)
            s_next = _safe_float(next_sec.get("s"), 0.0)
            boundary_s = s_next

            prev_offset = _lane_offset_at(road, max(0.0, boundary_s - eps_s))
            next_offset = _lane_offset_at(road, boundary_s + eps_s)
            if prev_offset is not None and next_offset is not None:
                delta = abs(next_offset - prev_offset)
                if delta > lane_offset_eps:
                    report["issues"].append(
                        {
                            "type": "lane_offset",
                            "road_id": road_id,
                            "boundary_s": boundary_s,
                            "delta": delta,
                            "prev": prev_offset,
                            "next": next_offset,
                            "threshold": lane_offset_eps,
                        }
                    )

            prev_lanes = _collect_lanes(prev_sec)
            next_lanes = _collect_lanes(next_sec)
            for lane_id in sorted(set(prev_lanes.keys()) & set(next_lanes.keys())):
                prev_lane = prev_lanes[lane_id]
                next_lane = next_lanes[lane_id]
                s_rel_prev = max(0.0, (boundary_s - eps_s) - s_prev)
                s_rel_next = max(0.0, (boundary_s + eps_s) - s_next)
                prev_w = _lane_width_at(prev_lane, s_rel_prev)
                next_w = _lane_width_at(next_lane, s_rel_next)
                if prev_w is None or next_w is None:
                    continue
                delta = abs(next_w - prev_w)
                if delta > lane_width_eps:
                    report["issues"].append(
                        {
                            "type": "lane_width",
                            "road_id": road_id,
                            "lane_id": lane_id,
                            "boundary_s": boundary_s,
                            "delta": delta,
                            "prev": prev_w,
                            "next": next_w,
                            "threshold": lane_width_eps,
                        }
                    )

    report["n_issues"] = len(report["issues"])
    report["ok"] = report["n_issues"] == 0
    return report


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Lane geometry continuity check")
    ap.add_argument("xodr_path", help="Path to OpenDRIVE file")
    ap.add_argument("--lane-offset-eps", type=float, default=None)
    ap.add_argument("--lane-width-eps", type=float, default=None)
    args = ap.parse_args()

    rep = check_lane_geometry_continuity(
        args.xodr_path,
        lane_offset_eps=args.lane_offset_eps,
        lane_width_eps=args.lane_width_eps,
    )
    print(json.dumps(rep, indent=2, ensure_ascii=True))
