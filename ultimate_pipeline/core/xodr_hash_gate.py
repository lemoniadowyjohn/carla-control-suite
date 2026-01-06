#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage hash + stats gate (reproducibility).

Computes:
- MD5 (file bytes)
- counts: roads, laneSections, driving lanes, junctions, signals, objects
- simple topology signature: road-link connected components and dangling refs

Offline, deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from typing import Dict, Any, Set, List


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_driving_lanes(root: ET.Element) -> int:
    return sum(1 for lane in root.findall(".//lane") if lane.get("type") == "driving")


def _road_graph_components(root: ET.Element) -> Dict[str, Any]:
    roads = {r.get("id") for r in root.findall(".//road") if r.get("id") is not None}
    adj: Dict[str, Set[str]] = {rid: set() for rid in roads}
    dangling = 0

    for r in root.findall(".//road"):
        rid = r.get("id")
        if rid not in roads:
            continue
        link = r.find("link")
        if link is None:
            continue
        for tag in ("predecessor", "successor"):
            e = link.find(tag)
            if e is None:
                continue
            tgt = e.get("elementId") or e.get("id") or e.get("road") or e.get("element_id")
            if not tgt:
                continue
            if tgt in roads:
                adj[rid].add(tgt)
                adj[tgt].add(rid)
            else:
                dangling += 1

    seen: Set[str] = set()
    comp_sizes: List[int] = []
    for rid in roads:
        if rid in seen:
            continue
        stack = [rid]
        seen.add(rid)
        sz = 0
        while stack:
            u = stack.pop()
            sz += 1
            for v in adj.get(u, ()):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comp_sizes.append(sz)
    comp_sizes.sort(reverse=True)
    return {
        "components": len(comp_sizes),
        "largest_component_size": comp_sizes[0] if comp_sizes else 0,
        "dangling_road_link_refs": dangling,
    }


def compute_gate(xodr_path: str) -> Dict[str, Any]:
    root = ET.parse(xodr_path).getroot()
    g = {
        "md5": md5_file(xodr_path),
        "roads": len(root.findall(".//road")),
        "laneSections": len(root.findall(".//laneSection")),
        "driving_lanes": _count_driving_lanes(root),
        "junctions": len(root.findall(".//junction")),
        "signals": len(root.findall(".//signal")),
        "objects": len(root.findall(".//object")),
    }
    g["topology_signature"] = _road_graph_components(root)
    return g


def write_gate(xodr_path: str, json_out: str) -> None:
    os.makedirs(os.path.dirname(json_out), exist_ok=True)
    g = compute_gate(xodr_path)
    g["xodr_path"] = xodr_path
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(g, f, indent=2)


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("xodr")
    ap.add_argument("--json_out", required=True)
    args = ap.parse_args()
    write_gate(args.xodr, args.json_out)


if __name__ == "__main__":
    _cli()
