#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lane-link target existence gate.

Purpose:
- Offline, deterministic sanity check: lane-level predecessor/successor IDs must refer
  to lanes that exist in the adjacent laneSection (when an adjacent laneSection exists).

This prevents a common class of downstream failures where a lane references a target
lane ID that is missing, causing later tooling (and sometimes CARLA import paths) to
misbehave.

Notes:
- This gate is *tile-safe*: it does NOT require "global routability".
- Dead-ends are allowed: if a laneSection has no predecessor/successor laneSection,
  we do not mark missing links as an error (unless you set allow_dead_ends=False).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Iterable, List, Optional, Tuple


@dataclass
class Issue:
    road_id: str
    lane_section_s: str
    lane_id: str
    direction: str  # "predecessor" | "successor"
    target_lane_id: int | str
    message: str




def _maybe_int(value: str) -> int | str:
    """Convert numeric-looking lane IDs to int for stable JSON and tests."""
    try:
        return int(value)
    except Exception:
        return value

def _lane_sections_in_order(road: ET.Element) -> List[ET.Element]:
    lanes = road.find("lanes")
    if lanes is None:
        return []
    lane_sections = list(lanes.findall("laneSection"))
    # Sort by numeric s if present
    def _s(ls: ET.Element) -> float:
        try:
            return float(ls.get("s", "0") or "0")
        except Exception:
            return 0.0
    lane_sections.sort(key=_s)
    return lane_sections


def check_lane_link_targets_exist(
    xodr_path: str,
    lane_types: Tuple[str, ...] = ("driving",),
    allow_dead_ends: bool = True,
    max_issues: int = 2000,
) -> Dict[str, Any]:
    """
    Returns a report dict with keys:
      ok, num_issues, issues (truncated), totals
    """
    p = Path(xodr_path)
    tree = ET.parse(str(p))
    root = tree.getroot()

    issues: List[Issue] = []
    roads = list(root.findall("road"))

    for road in roads:
        road_id = road.get("id", "UNKNOWN")
        lsecs = _lane_sections_in_order(road)
        if not lsecs:
            continue

        # Precompute lane-id sets per laneSection index
        lane_ids_per_sec: List[set[str]] = []
        for ls in lsecs:
            ids = set()
            for lane in ls.findall(".//lane"):
                lid = lane.get("id")
                if lid is not None:
                    ids.add(lid)
            lane_ids_per_sec.append(ids)

        for i, ls in enumerate(lsecs):
            ls_s = ls.get("s", "0") or "0"
            for lane in ls.findall(".//lane"):
                lane_type = lane.get("type", "")
                if lane_types and lane_type not in lane_types:
                    continue

                lane_id = lane.get("id", "")
                link = lane.find("link")
                if link is None:
                    continue

                # predecessor: should exist in previous laneSection (if it exists)
                pred = link.find("predecessor")
                if pred is not None:
                    target_id = pred.get("id")
                    if target_id:
                        if i == 0:
                            if not allow_dead_ends:
                                issues.append(Issue(
                                    road_id=road_id,
                                    lane_section_s=ls_s,
                                    lane_id=lane_id,
                                    direction="predecessor",
                                    target_lane_id=_maybe_int(target_id),
                                    message="predecessor link present but no previous laneSection exists",
                                ))
                        else:
                            if target_id not in lane_ids_per_sec[i - 1]:
                                issues.append(Issue(
                                    road_id=road_id,
                                    lane_section_s=ls_s,
                                    lane_id=lane_id,
                                    direction="predecessor",
                                    target_lane_id=_maybe_int(target_id),
                                    message="predecessor target lane id not found in previous laneSection",
                                ))

                # successor: should exist in next laneSection (if it exists)
                succ = link.find("successor")
                if succ is not None:
                    target_id = succ.get("id")
                    if target_id:
                        if i == len(lsecs) - 1:
                            if not allow_dead_ends:
                                issues.append(Issue(
                                    road_id=road_id,
                                    lane_section_s=ls_s,
                                    lane_id=lane_id,
                                    direction="successor",
                                    target_lane_id=_maybe_int(target_id),
                                    message="successor link present but no next laneSection exists",
                                ))
                        else:
                            if target_id not in lane_ids_per_sec[i + 1]:
                                issues.append(Issue(
                                    road_id=road_id,
                                    lane_section_s=ls_s,
                                    lane_id=lane_id,
                                    direction="successor",
                                    target_lane_id=_maybe_int(target_id),
                                    message="successor target lane id not found in next laneSection",
                                ))

                if len(issues) >= max_issues:
                    break
            if len(issues) >= max_issues:
                break
        if len(issues) >= max_issues:
            break

    report = {
        "ok": len(issues) == 0,
        "num_issues": len(issues),
        "issues": [issue.__dict__ for issue in issues[:min(len(issues), max_issues)]],
        "totals": {
            "roads_scanned": len(roads),
            "lane_types": list(lane_types),
            "allow_dead_ends": bool(allow_dead_ends),
            "max_issues": int(max_issues),
        },
        "xodr_path": str(p),
    }
    return report




def repair_drop_invalid_lane_links(
    in_xodr_path: str,
    out_xodr_path: str,
    lane_types: Tuple[str, ...] = ("driving",),
    allow_dead_ends: bool = True,
) -> Dict[str, Any]:
    """Repair helper: drop invalid predecessor/successor lane links.

    This is intentionally conservative: it only removes links whose target lane-id
    does not exist in the adjacent laneSection (when an adjacent laneSection exists).
    """
    inp = Path(in_xodr_path)
    outp = Path(out_xodr_path)
    tree = ET.parse(str(inp))
    root = tree.getroot()

    removed = 0
    roads = list(root.findall("road"))
    for road in roads:
        lsecs = _lane_sections_in_order(road)
        if not lsecs:
            continue

        # Precompute lane-id sets per laneSection index
        lane_ids_per_sec: List[set[str]] = []
        for ls in lsecs:
            ids: set[str] = set()
            for lane in ls.findall(".//lane"):
                lid = lane.get("id")
                if lid is not None:
                    ids.add(lid)
            lane_ids_per_sec.append(ids)

        for i, ls in enumerate(lsecs):
            for lane in ls.findall(".//lane"):
                lane_type = lane.get("type", "")
                if lane_types and lane_type not in lane_types:
                    continue
                link = lane.find("link")
                if link is None:
                    continue

                pred = link.find("predecessor")
                if pred is not None:
                    target_id = pred.get("id")
                    if target_id:
                        if i == 0:
                            if not allow_dead_ends:
                                link.remove(pred)
                                removed += 1
                        else:
                            if target_id not in lane_ids_per_sec[i - 1]:
                                link.remove(pred)
                                removed += 1

                succ = link.find("successor")
                if succ is not None:
                    target_id = succ.get("id")
                    if target_id:
                        if i == len(lsecs) - 1:
                            if not allow_dead_ends:
                                link.remove(succ)
                                removed += 1
                        else:
                            if target_id not in lane_ids_per_sec[i + 1]:
                                link.remove(succ)
                                removed += 1

                # If link element is now empty, remove it to keep output tidy.
                if link is not None and len(list(link)) == 0:
                    try:
                        lane.remove(link)
                    except Exception:
                        pass

    outp.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(outp), encoding="utf-8", xml_declaration=True)

    post = check_lane_link_targets_exist(str(outp), lane_types=lane_types, allow_dead_ends=allow_dead_ends)
    return {
        "in_path": str(inp),
        "out_path": str(outp),
        "removed_count": int(removed),
        "post_ok": bool(post.get("ok", False)),
        "post_num_issues": int(post.get("num_issues", 0) or 0),
    }

def assert_lane_link_targets_exist(
    xodr_path: str,
    lane_types: Tuple[str, ...] = ("driving",),
    allow_dead_ends: bool = True,
) -> Dict[str, Any]:
    rep = check_lane_link_targets_exist(xodr_path, lane_types=lane_types, allow_dead_ends=allow_dead_ends)
    if not rep.get("ok", False):
        raise RuntimeError(f"lane_link_targets_exist failed: {rep.get('num_issues')} issues")
    return rep


def write_report(rep: Dict[str, Any], out_json: str) -> str:
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    return out_json


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--allow_dead_ends", type=int, default=1)
    args = ap.parse_args()

    r = check_lane_link_targets_exist(args.xodr, allow_dead_ends=bool(args.allow_dead_ends))
    if args.out:
        write_report(r, args.out)
    print(json.dumps({"ok": r["ok"], "num_issues": r["num_issues"]}, indent=2))
    raise SystemExit(0 if r["ok"] else 2)
