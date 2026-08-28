# ultimate_pipeline/quality/check_lane_width_continuity.py
# -*- coding: utf-8 -*-

"""
Lane width continuity check at laneSection boundaries.

Flags:
- Non-positive widths.
- Sudden width jumps across consecutive laneSections for the same lane id.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def _width_at_s(widths: List[ET.Element], s_local: float) -> Optional[float]:
    if not widths:
        return None
    widths_sorted = sorted(widths, key=lambda w: _safe_float(w.get("sOffset")))
    current = None
    for w in widths_sorted:
        if _safe_float(w.get("sOffset")) <= s_local + 1e-9:
            current = w
        else:
            break
    if current is None:
        return None
    s_offset = _safe_float(current.get("sOffset"))
    ds = max(0.0, s_local - s_offset)
    a = _safe_float(current.get("a"), 0.0)
    b = _safe_float(current.get("b"), 0.0)
    c = _safe_float(current.get("c"), 0.0)
    d = _safe_float(current.get("d"), 0.0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def check_lane_width_continuity(
    xodr_path: str,
    min_width: float = 0.01,
    max_jump: float = 1.0,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": True,
        "min_width": min_width,
        "max_jump": max_jump,
        "num_roads": 0,
        "num_issues": 0,
        "issues": [],
        "warnings": [],
    }

    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception as e:
        report["ok"] = False
        report["warnings"].append(f"failed to parse xodr: {e}")
        return report

    roads = root.findall("road")
    report["num_roads"] = len(roads)
    issues: List[Dict[str, Any]] = []

    for road in roads:
        rid = (road.get("id") or "").strip()
        road_len = _safe_float(road.get("length"))
        lanes = road.find("lanes")
        if lanes is None:
            continue

        lane_sections = lanes.findall("laneSection")
        if not lane_sections:
            continue

        sections_with_s: List[Tuple[float, ET.Element]] = []
        for ls in lane_sections:
            sections_with_s.append((_safe_float(ls.get("s")), ls))
        sections_with_s.sort(key=lambda t: t[0])

        for idx, (s0, ls) in enumerate(sections_with_s):
            s1 = road_len
            if idx + 1 < len(sections_with_s):
                s1 = sections_with_s[idx + 1][0]
            section_len = max(0.0, s1 - s0)

            for lane in ls.findall(".//lane"):
                lane_id = lane.get("id")
                widths = lane.findall("width")
                start_width = _width_at_s(widths, 0.0)
                # NaN/Inf from a corrupt width coefficient makes `start_width`
                # non-finite (but not None); `nan <= min_width` is always False in
                # IEEE-754, so this check would silently never fire without an
                # explicit guard.
                if start_width is not None and (not math.isfinite(start_width) or start_width <= min_width):
                    issues.append({
                        "type": "nonpositive_width",
                        "road": rid,
                        "lane": lane_id,
                        "laneSection_s": s0,
                        "width": start_width,
                    })

                if idx + 1 >= len(sections_with_s):
                    continue
                _, next_ls = sections_with_s[idx + 1]
                next_lane = next_ls.find(f".//lane[@id='{lane_id}']")
                if next_lane is None:
                    continue
                # Lane-type transition (e.g. sidewalk <-> driving between
                # adjacent lane sections) means the lane's identity changes;
                # comparing widths across it is a false positive (road 46620,
                # DEEP_QUALITY_SWEEP 20260817). Only compare same-type lanes.
                if next_lane.get("type") != lane.get("type"):
                    continue
                next_widths = next_lane.findall("width")
                end_width = _width_at_s(widths, section_len)
                next_start_width = _width_at_s(next_widths, 0.0)
                if end_width is None or next_start_width is None:
                    continue

                delta = abs(next_start_width - end_width)
                # Same NaN/Inf-defeats-magnitude-comparison guard as above.
                if not math.isfinite(delta) or delta > max_jump:
                    issues.append({
                        "type": "width_jump",
                        "road": rid,
                        "lane": lane_id,
                        "laneSection_s": s0,
                        "next_laneSection_s": sections_with_s[idx + 1][0],
                        "width_end": end_width,
                        "width_start": next_start_width,
                        "delta": delta,
                    })

    report["issues"] = issues
    report["num_issues"] = len(issues)
    report["ok"] = len(issues) == 0
    return report


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Check lane width continuity at laneSection boundaries")
    ap.add_argument("xodr_path")
    ap.add_argument("--min-width", type=float, default=0.01)
    ap.add_argument("--max-jump", type=float, default=1.0)
    args = ap.parse_args()

    rep = check_lane_width_continuity(args.xodr_path, min_width=args.min_width, max_jump=args.max_jump)
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
