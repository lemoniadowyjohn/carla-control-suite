#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-invariants scanner + fixer for OpenDRIVE.

CARLA can crash natively (assert: s >= 0.0) if any 's' / 'sOffset' is negative,
or if key 's' sequences are non-monotonic.

This module is offline and deterministic.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

S_ATTR_TARGETS: Tuple[Tuple[str, str], ...] = (
    (".//road/planView/geometry", "s"),
    (".//road/lanes/laneSection", "s"),
    (".//road/lanes/laneOffset", "s"),
    (".//road/elevationProfile/elevation", "s"),
    (".//road/lateralProfile/superelevation", "s"),
    (".//road/lanes/laneSection//lane/width", "sOffset"),
    (".//road/lanes/laneSection//lane/border", "sOffset"),
    (".//road/objects/object", "s"),
    (".//road/signals/signal", "s"),
    (".//road/type", "s"),
    (".//road/type/speed", "s"),
)

MONO_SEQUENCE_XPATHS: Tuple[str, ...] = (
    "./planView/geometry",
    "./lanes/laneSection",
    "./elevationProfile/elevation",
    "./lateralProfile/superelevation",
    "./lanes/laneOffset",
)

EPS = 1e-9
TOL_CLAMP = 1e-6  # clamp tiny negatives to 0


@dataclass
class SInvariantReport:
    negative_s_count: int
    negative_s_examples: List[Tuple[str, str, float]]
    monotonic_issues: List[Tuple[str, List[float]]]

    def to_dict(self) -> Dict:
        return {
            "negative_s_count": self.negative_s_count,
            "negative_s_examples": [list(x) for x in self.negative_s_examples],
            "monotonic_issues": [[xpath, vals] for (xpath, vals) in self.monotonic_issues],
        }


def _f(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def scan_s_invariants(xodr_path: str) -> SInvariantReport:
    root = ET.parse(xodr_path).getroot()

    neg: List[Tuple[str, str, float]] = []
    for xpath, attr in S_ATTR_TARGETS:
        for e in root.findall(xpath):
            v = _f(e.get(attr))
            if v is None:
                continue
            if v < 0.0:
                neg.append((xpath, attr, v))

    mono: List[Tuple[str, List[float]]] = []
    for road in root.findall(".//road"):
        rid = road.get("id", "?")
        for rel in MONO_SEQUENCE_XPATHS:
            seq = road.findall(rel)
            if not seq:
                continue
            vals = []
            for e in seq:
                v = _f(e.get("s"))
                if v is not None:
                    vals.append(v)
            if len(vals) >= 2:
                ok = all(vals[i] <= vals[i+1] + EPS for i in range(len(vals)-1))
                if not ok:
                    mono.append((f"road[{rid}]::{rel}", vals[:50]))
    return SInvariantReport(len(neg), neg[:20], mono[:20])


def fix_s_invariants(
    in_xodr: str,
    out_xodr: str,
    *,
    clamp_tiny: bool = True,
    verbose: bool = False,
) -> Dict:
    """Deterministic fixer (per-road):

    - Compute min_s over key elements within each road.
    - If min_s < 0, shift all relevant 's' attributes by -min_s.
    - Clamp sOffset to >= 0 (safe).
    - Clamp tiny negative s values to 0.

    Returns dict with before/after reports.
    """
    before = scan_s_invariants(in_xodr).to_dict()

    tree = ET.parse(in_xodr)
    root = tree.getroot()

    def shift_elem_s(e: ET.Element, shift: float) -> None:
        v = _f(e.get("s"))
        if v is None:
            return
        nv = v + shift
        if clamp_tiny and nv < 0.0 and abs(nv) <= 1e-3:
            nv = 0.0
        e.set("s", f"{nv:.8f}")

    def clamp_offset(e: ET.Element) -> None:
        v = _f(e.get("sOffset"))
        if v is None:
            return
        e.set("sOffset", f"{max(0.0, v):.8f}")

    for road in root.findall(".//road"):
        # collect min s from key road-local elements
        min_s = None
        for rel in [
            "./planView/geometry",
            "./lanes/laneSection",
            "./lanes/laneOffset",
            "./elevationProfile/elevation",
            "./lateralProfile/superelevation",
            "./objects/object",
            "./signals/signal",
            "./type",
        ]:
            for e in road.findall(rel):
                v = _f(e.get("s"))
                if v is None:
                    continue
                if min_s is None or v < min_s:
                    min_s = v

        if min_s is None:
            continue

        shift = -min_s if min_s < 0.0 else 0.0
        if verbose and shift != 0.0:
            rid = road.get("id", "?")
            print(f"[s_fix] road {rid}: shift +{shift:.8f} (min_s={min_s:.8f})")

        if shift != 0.0:
            # shift s attributes for common offenders
            for rel in [
                "./planView/geometry",
                "./lanes/laneSection",
                "./lanes/laneOffset",
                "./elevationProfile/elevation",
                "./lateralProfile/superelevation",
                "./objects/object",
                "./signals/signal",
                "./type",
                "./type/speed",
            ]:
                for e in road.findall(rel):
                    if e.get("s") is not None:
                        shift_elem_s(e, shift)

        # ------------------------------------------------------------------
        # Clamp/sort laneSections per road length (CARLA-critical)
        # ------------------------------------------------------------------
        try:
            road_len = _f(road.get("length"))
            road_len = float(road_len) if road_len is not None else 0.0
        except Exception:
            road_len = 0.0

        lanes_parent = road.find("./lanes")
        if lanes_parent is not None:
            try:
                lane_sections = lanes_parent.findall("./laneSection")
                if lane_sections:
                    # clamp to [0, road_len]
                    for ls in lane_sections:
                        sv = _f(ls.get("s"))
                        if sv is None:
                            continue
                        if sv < 0.0:
                            ls.set("s", "0.0")
                        elif 0.0 < road_len < sv:
                            # keep strictly inside length if possible
                            eps = min(0.05, max(1e-4, road_len * 0.01))
                            ls.set("s", f"{max(0.0, road_len - eps):.8f}")

                    # sort and reinsert deterministically
                    lane_sections_sorted = sorted(lane_sections, key=lambda e: _f(e.get("s")) or 0.0)
                    # remove existing laneSections
                    for ls in lane_sections:
                        lanes_parent.remove(ls)
                    # insert them before first non-laneSection child to preserve ordering
                    children = list(lanes_parent)
                    insert_idx = 0
                    for idx, ch in enumerate(children):
                        if ch.tag != "laneSection":
                            insert_idx = idx
                            break
                        insert_idx = idx + 1
                    for offset, ls in enumerate(lane_sections_sorted):
                        lanes_parent.insert(insert_idx + offset, ls)

                    # ensure first laneSection starts at 0
                    first = lane_sections_sorted[0]
                    fs = _f(first.get("s"))
                    if fs is not None and fs > 1e-6:
                        first.set("s", "0.0")

                    # enforce monotonic strictly non-decreasing
                    prev_s = None
                    eps_mono = min(1e-3, max(1e-6, road_len * 1e-6))
                    for ls in lane_sections_sorted:
                        sv = _f(ls.get("s"))
                        if sv is None:
                            continue
                        if prev_s is not None and sv < prev_s:
                            ls.set("s", f"{prev_s + eps_mono:.8f}")
                            sv = prev_s + eps_mono
                        prev_s = sv
            except Exception:
                # never crash the pipeline due to invariants fixer
                pass

        # always clamp offsets inside this road
        for e in road.findall(".//lane/width"):
            if e.get("sOffset") is not None:
                clamp_offset(e)
        for e in road.findall(".//lane/border"):
            if e.get("sOffset") is not None:
                clamp_offset(e)

        # clamp tiny negative s even if no shift
        if clamp_tiny:
            for rel in [
                "./planView/geometry",
                "./lanes/laneSection",
                "./lanes/laneOffset",
                "./elevationProfile/elevation",
                "./lateralProfile/superelevation",
            ]:
                for e in road.findall(rel):
                    v = _f(e.get("s"))
                    if v is None:
                        continue
                    if v < 0.0 and abs(v) <= 1e-3:
                        e.set("s", "0.0")

    os.makedirs(os.path.dirname(out_xodr), exist_ok=True)
    tree.write(out_xodr, encoding="utf-8", xml_declaration=True)

    after = scan_s_invariants(out_xodr).to_dict()
    return {"before": before, "after": after, "out_xodr": out_xodr}
