#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tile Forensics + Emergency Repair (OpenDRIVE XODR)

Purpose:
- Detect common reasons why CARLA returns 0 waypoints / spawn fails.
- Specifically detect the "lane type wiped" bug (all lanes type="none")
- Optionally apply an emergency patch to restore lane semantics for CARLA testing.

IMPORTANT:
- The emergency patch is a LAST-RESORT debug aid.
- Your thesis-grade fix is to preserve lane attributes during tiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json
import re
import xml.etree.ElementTree as ET


LANE_RE = re.compile(r"<lane\b", re.IGNORECASE)
ROAD_RE = re.compile(r"<road\b", re.IGNORECASE)
LANESECTION_RE = re.compile(r"<laneSection\b", re.IGNORECASE)
DRIVING_RE = re.compile(r'<lane\b[^>]*\btype="driving"\b', re.IGNORECASE)
NONE_RE = re.compile(r'<lane\b[^>]*\btype="none"\b', re.IGNORECASE)


@dataclass
class TileScan:
    path: str
    roads: int
    lane_sections: int
    lanes_total: int
    lanes_driving: int
    lanes_none: int
    size_kb: float
    classification: str
    signature: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def scan_tile(tile_path: str) -> TileScan:
    p = Path(tile_path)
    txt = _read_text(p)

    roads = len(ROAD_RE.findall(txt))
    lane_sections = len(LANESECTION_RE.findall(txt))
    lanes_total = len(LANE_RE.findall(txt))
    lanes_driving = len(DRIVING_RE.findall(txt))
    lanes_none = len(NONE_RE.findall(txt))
    size_kb = round(p.stat().st_size / 1024.0, 1)

    # Classify
    if roads == 0:
        classification = "empty_tile"
    elif lanes_driving > 0:
        classification = "drivable_semantics_present"
    else:
        classification = "nondrivable_semantics"

    # Detect signatures (root-cause fingerprints)
    signature = "unknown"
    if roads > 0 and lanes_total > 0 and lanes_driving == 0:
        none_ratio = (lanes_none / max(1, lanes_total))
        if none_ratio >= 0.9:
            signature = "lane_type_wiped_all_none"
        else:
            signature = "no_driving_lanes_mixed_types_or_missing"
    elif roads > 0 and lanes_total == 0:
        signature = "roads_but_no_lanes"
    elif roads == 0:
        signature = "empty"

    return TileScan(
        path=str(p),
        roads=roads,
        lane_sections=lane_sections,
        lanes_total=lanes_total,
        lanes_driving=lanes_driving,
        lanes_none=lanes_none,
        size_kb=size_kb,
        classification=classification,
        signature=signature,
    )


def scan_tiles_dir(tiles_dir: str) -> Dict:
    tiles_dir_p = Path(tiles_dir)
    tiles = sorted(tiles_dir_p.glob("*.xodr"))

    scans = [scan_tile(str(t)) for t in tiles]

    by_sig: Dict[str, int] = {}
    by_class: Dict[str, int] = {}
    for s in scans:
        by_sig[s.signature] = by_sig.get(s.signature, 0) + 1
        by_class[s.classification] = by_class.get(s.classification, 0) + 1

    return {
        "tiles_dir": str(tiles_dir_p),
        "tile_count": len(scans),
        "summary_by_signature": by_sig,
        "summary_by_classification": by_class,
        "tiles": [s.__dict__ for s in scans],
    }


# -----------------------------
# Emergency repair (optional)
# -----------------------------

def _lane_has_width(lane_elem: ET.Element) -> bool:
    # OpenDRIVE: <lane><width .../></lane>
    return lane_elem.find("width") is not None


def _lane_has_roadmark(lane_elem: ET.Element) -> bool:
    return lane_elem.find("roadMark") is not None


def emergency_repair_lane_types(tile_in: str, tile_out: str) -> Dict:
    """
    Emergency patch: if lanes are type="none", promote non-center lanes to type="driving"
    when they look like actual lanes (width or roadMark present).

    Rules:
    - Keep lane id="0" as type="none" (center lane).
    - For lane id != 0:
        if type=="none" and (has width OR has roadMark) => set type="driving"
    """
    tree = ET.parse(tile_in)
    root = tree.getroot()

    changed = 0
    inspected = 0

    for lane in root.findall(".//lane"):
        inspected += 1
        lane_id = lane.get("id", "")
        lane_type = lane.get("type", "")

        if lane_id == "0":
            # center lane should not be driving
            continue

        if lane_type.lower() == "none":
            if _lane_has_width(lane) or _lane_has_roadmark(lane):
                lane.set("type", "driving")
                changed += 1

    Path(tile_out).parent.mkdir(parents=True, exist_ok=True)
    tree.write(tile_out, encoding="utf-8", xml_declaration=True)

    return {
        "tile_in": tile_in,
        "tile_out": tile_out,
        "lanes_inspected": inspected,
        "lanes_type_changed_to_driving": changed,
    }


def emergency_repair_tiles_dir(
    tiles_dir: str,
    out_dir: str,
    only_if_signature: str = "lane_type_wiped_all_none",
) -> Dict:
    tiles_dir_p = Path(tiles_dir)
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)

    scans = [scan_tile(str(p)) for p in sorted(tiles_dir_p.glob("*.xodr"))]

    repaired: List[Dict] = []
    skipped: List[str] = []

    for s in scans:
        src = s.path
        dst = str(out_dir_p / Path(src).name)

        if s.signature != only_if_signature:
            # Copy as-is (or skip, depending on your preference)
            Path(dst).write_text(_read_text(Path(src)), encoding="utf-8", errors="ignore")
            skipped.append(src)
            continue

        repaired.append(emergency_repair_lane_types(src, dst))

    return {
        "tiles_dir_in": str(tiles_dir_p),
        "tiles_dir_out": str(out_dir_p),
        "repaired_tiles": repaired,
        "copied_or_skipped_tiles": len(skipped),
        "signature_repaired": only_if_signature,
    }


def write_report(report: Dict, out_path: str) -> str:
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return str(out_p)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", required=True, help="Tiles directory containing *.xodr")
    ap.add_argument("--report", default="tile_forensics_report.json")
    ap.add_argument("--repair", action="store_true", help="Apply emergency repair into --repair_out")
    ap.add_argument("--repair_out", default="tiles_repaired")
    args = ap.parse_args()

    rep = scan_tiles_dir(args.tiles)
    write_report(rep, args.report)
    print(f"[OK] Wrote report: {args.report}")

    if args.repair:
        fix = emergency_repair_tiles_dir(args.tiles, args.repair_out)
        fix_path = Path(args.report).with_name("tile_forensics_repair.json")
        write_report(fix, str(fix_path))
        print(f"[OK] Wrote repair log: {fix_path}")
        print(f"[OK] Repaired tiles dir: {args.repair_out}")
