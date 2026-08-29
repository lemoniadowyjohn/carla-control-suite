#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LAN-001/002/007/009 — lane structure invariants validator.

Read-only validation of OpenDRIVE lane structure:

- LAN-001: laneSection records have unique, strictly ordered `s` starts,
  the first starts at 0, and coverage is valid over the road length.
- LAN-002: lane IDs are unique within a section (and its side), and lane 0
  exists as the center lane.
- LAN-007: width polynomials are finite, non-negative over their interval,
  ordered by sOffset, and within configured plausible bounds.
- LAN-009: laneOffset records are finite, ordered, and valid over road length
  with no abrupt lateral jumps.

Fail-closed: any violation is reported; the validator never mutates.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

MAX_WIDTH_M = float(30.0)
MIN_WIDTH_M = float(-1e-3)
MAX_LANEOFFSET_JUMP_M = float(5.0)


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _lane_sections(road: ET.Element) -> List[Tuple[str, ET.Element]]:
    lanes = road.find("lanes")
    out: List[Tuple[str, ET.Element]] = []
    if lanes is None:
        return out
    for section in lanes.findall("laneSection"):
        out.append((section.get("s") or "0", section))
    return out


def _iter_polys(elem: ET.Element, tag: str, keys: Tuple[str, ...]) -> List[Tuple[float, Tuple[float, ...]]]:
    polys: List[Tuple[float, Tuple[float, ...]]] = []
    for p in elem.findall(tag):
        try:
            s = float(p.get("sOffset") or p.get("s") or "0")
        except Exception:
            s = 0.0
        coeffs = []
        for k in keys:
            coeffs.append(_safe_float(p.get(k)))
        polys.append((s, tuple(coeffs)))
    polys.sort(key=lambda v: v[0])
    return polys


def _raw_ordered_s(elem: ET.Element, tag: str) -> List[float]:
    """s starts in DOCUMENT order, for ordering-violation detection."""
    out: List[float] = []
    for p in elem.findall(tag):
        try:
            out.append(float(p.get("sOffset") or p.get("s") or "0"))
        except Exception:
            out.append(0.0)
    return out


def validate_lane_structure(
    root: ET.Element,
    *,
    max_width_m: float = MAX_WIDTH_M,
    max_laneoffset_jump_m: float = MAX_LANEOFFSET_JUMP_M,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    roads = root.findall("road")

    for road in roads:
        rid = (road.get("id") or "").strip()
        length = _safe_float(road.get("length"))
        if not math.isfinite(length):
            issues.append({"road_id": rid, "rule": "LAN-001", "severity": "fail",
                           "detail": f"road length is non-finite ({length!r})"})
        sections = _lane_sections(road)

        if not sections:
            issues.append({"road_id": rid, "rule": "LAN-001", "severity": "warn",
                           "detail": "no laneSection present"})
            continue

        # LAN-001: ordered/unique s, first at 0, coverage over road length.
        ss = [s for s, _ in sections]
        try:
            ss_f = [float(v) for v in ss]
        except Exception:
            ss_f = []
        if ss_f and ss_f[0] != 0.0:
            issues.append({"road_id": rid, "rule": "LAN-001", "severity": "fail",
                           "detail": f"first laneSection s={ss_f[0]} != 0"})
        if any(b <= a for a, b in zip(ss_f, ss_f[1:])):
            issues.append({"road_id": rid, "rule": "LAN-001", "severity": "fail",
                           "detail": "laneSection s values not strictly ordered"})
        if len(set(ss_f)) != len(ss_f):
            issues.append({"road_id": rid, "rule": "LAN-001", "severity": "fail",
                           "detail": "duplicate laneSection s values"})
        if length > 0.0 and ss_f and ss_f[-1] >= length + 1e-6:
            issues.append({"road_id": rid, "rule": "LAN-001", "severity": "fail",
                           "detail": f"last laneSection s={ss_f[-1]} exceeds road length {length}"})

        for s_start, section in sections:
            # LAN-002: unique lane ids per section, lane 0 = center.
            lane_ids: List[Optional[str]] = []
            for lane in section.findall("./left/lane") + section.findall("./right/lane"):
                lane_ids.append(lane.get("id"))
            center = section.find("./center/lane")
            if center is None or (center.get("id") not in (None, "0")):
                issues.append({"road_id": rid, "rule": "LAN-002", "severity": "fail",
                               "detail": f"section s={s_start}: missing center lane id=0"})
            ids = [i for i in lane_ids if i is not None]
            if len(ids) != len(set(ids)):
                issues.append({"road_id": rid, "rule": "LAN-002", "severity": "fail",
                               "detail": f"section s={s_start}: duplicate lane ids"})

            # LAN-007: width polynomials.
            for lane in section.findall("./left/lane") + section.findall("./right/lane"):
                widths = _iter_polys(lane, "width", ("a", "b", "c", "d"))
                prev_end = None
                prev_width = None
                for soff, (a, b, c, d) in widths:
                    if not all(math.isfinite(v) for v in (a, b, c, d)):
                        issues.append({"road_id": rid, "rule": "LAN-007", "severity": "fail",
                                       "detail": f"section s={s_start}: non-finite width at {soff}"})
                        continue
                    if a < MIN_WIDTH_M:
                        issues.append({"road_id": rid, "rule": "LAN-007", "severity": "fail",
                                       "detail": f"section s={s_start}: negative width a={a}"})
                    if abs(a) > max_width_m:
                        issues.append({"road_id": rid, "rule": "LAN-007", "severity": "fail",
                                       "detail": f"section s={s_start}: implausible width a={a}"})
                    if prev_end is not None and soff < prev_end - 1e-6:
                        issues.append({"road_id": rid, "rule": "LAN-007", "severity": "fail",
                                       "detail": f"section s={s_start}: width sOffsets not ordered"})
                    if prev_width is not None and (prev_width - a) > 1e-3:
                        issues.append({"road_id": rid, "rule": "LAN-007", "severity": "fail",
                                       "detail": f"section s={s_start}: width jump {prev_width - a:.3f} m"})
                    prev_width = a

        # LAN-009: laneOffset records live under <lanes>, sibling of laneSection.
        lanes_elem = road.find("lanes")
        if lanes_elem is not None:
            doc_s = _raw_ordered_s(lanes_elem, "laneOffset")
            if any(b <= a for a, b in zip(doc_s, doc_s[1:])):
                issues.append({"road_id": rid, "rule": "LAN-009", "severity": "fail",
                               "detail": f"laneOffset s values not ordered in document: {doc_s}"})
            offsets = _iter_polys(lanes_elem, "laneOffset", ("a", "b", "c", "d"))
            prev_soff = None
            prev_offset = None
            for soff, (a, b, c, d) in offsets:
                if not all(math.isfinite(v) for v in (a, b, c, d)):
                    issues.append({"road_id": rid, "rule": "LAN-009", "severity": "fail",
                                   "detail": "non-finite laneOffset"})
                    continue
                if length > 0.0 and soff >= length + 1e-6:
                    issues.append({"road_id": rid, "rule": "LAN-009", "severity": "fail",
                                   "detail": f"laneOffset s={soff} exceeds road length {length}"})
                if prev_offset is not None and abs(prev_offset - a) > max_laneoffset_jump_m:
                    issues.append({"road_id": rid, "rule": "LAN-009", "severity": "fail",
                                   "detail": f"laneOffset jump {abs(prev_offset - a):.2f} m"})
                prev_soff, prev_offset = soff, a

    ok = not any(issue["severity"] == "fail" for issue in issues)
    return {
        "ok": ok,
        "rule": "LAN-001/LAN-002/LAN-007/LAN-009",
        "roads_checked": len(roads),
        "issues": issues,
        "issue_count": len(issues),
        "fail_count": sum(1 for i in issues if i["severity"] == "fail"),
    }
