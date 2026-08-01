# ultimate_pipeline/quality/check_post_tiling_integrity.py
# -*- coding: utf-8 -*-

"""
Post-tiling integrity and seam sanity checks.

Checks:
- Uniqueness of road IDs, junction IDs, signal IDs.
- Junction connections reference existing roads.
- Orphan road links (predecessor/successor to missing roads).
- Seam endpoint sanity via geometric continuity at road joins.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set, Tuple

from ultimate_pipeline.quality.check_geometric_continuity import check_geometric_continuity


def _find_duplicate_ids(ids: List[str]) -> List[str]:
    seen: Set[str] = set()
    dupes: Set[str] = set()
    for item in ids:
        if item in seen:
            dupes.add(item)
        else:
            seen.add(item)
    return sorted(dupes)


def check_post_tiling_integrity(
    xodr_path: str,
    eps_xy: float = 0.05,
    eps_hdg: float = 0.01,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": True,
        "eps_xy": eps_xy,
        "eps_hdg": eps_hdg,
        "num_roads": 0,
        "num_junctions": 0,
        "num_signals": 0,
        "issues": [],
        "seam_endpoint_issues": [],
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
    road_ids = [(r.get("id") or "").strip() for r in roads if r.get("id")]

    junctions = root.findall("junction")
    report["num_junctions"] = len(junctions)
    junction_ids = [(j.get("id") or "").strip() for j in junctions if j.get("id")]

    signals = root.findall(".//signal")
    report["num_signals"] = len(signals)
    signal_ids = [(s.get("id") or "").strip() for s in signals if s.get("id")]

    dup_roads = _find_duplicate_ids(road_ids)
    dup_junctions = _find_duplicate_ids(junction_ids)
    dup_signals = _find_duplicate_ids(signal_ids)

    if dup_roads:
        report["issues"].append({"type": "duplicate_road_ids", "ids": dup_roads})
    if dup_junctions:
        report["issues"].append({"type": "duplicate_junction_ids", "ids": dup_junctions})
    if dup_signals:
        report["issues"].append({"type": "duplicate_signal_ids", "ids": dup_signals})

    road_id_set = set(road_ids)

    # Junction connection references
    for junction in junctions:
        jid = (junction.get("id") or "").strip()
        for conn in junction.findall("connection"):
            incoming = (conn.get("incomingRoad") or "").strip()
            connecting = (conn.get("connectingRoad") or "").strip()
            if incoming and incoming not in road_id_set:
                report["issues"].append({
                    "type": "junction_missing_incoming_road",
                    "junction": jid,
                    "road": incoming,
                })
            if connecting and connecting not in road_id_set:
                report["issues"].append({
                    "type": "junction_missing_connecting_road",
                    "junction": jid,
                    "road": connecting,
                })

    # Orphan links
    for road in roads:
        rid = (road.get("id") or "").strip()
        link = road.find("link")
        if link is None:
            continue
        for kind in ("predecessor", "successor"):
            el = link.find(kind)
            if el is None:
                continue
            etype = (el.get("elementType") or "").strip()
            eid = (el.get("elementId") or "").strip()
            if etype == "road" and eid and eid not in road_id_set:
                report["issues"].append({
                    "type": "orphan_road_link",
                    "from_road": rid,
                    "to_road": eid,
                    "link_kind": kind,
                })

    seam_report = check_geometric_continuity(xodr_path, eps_xy=eps_xy, eps_hdg=eps_hdg)
    seam_issues = seam_report.get("issues", [])
    if seam_issues:
        report["seam_endpoint_issues"] = seam_issues

    report["ok"] = len(report["issues"]) == 0 and len(report["seam_endpoint_issues"]) == 0
    return report


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Post-tiling integrity check for OpenDRIVE map")
    ap.add_argument("xodr_path")
    ap.add_argument("--eps-xy", type=float, default=0.05)
    ap.add_argument("--eps-hdg", type=float, default=0.01)
    args = ap.parse_args()

    rep = check_post_tiling_integrity(args.xodr_path, eps_xy=args.eps_xy, eps_hdg=args.eps_hdg)
    print(json.dumps(rep, indent=2))
    sys.exit(0 if rep.get("ok", False) else 2)
