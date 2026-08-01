#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CARLA crash hardener for OpenDRIVE (.xodr).

Applies conservative, deterministic fixes known to trigger CARLA 0.9.16 Windows crashes:
- Remove degenerate roadMark lines (length=0 and space=0)
- Zero laneOffset polynomials on junction connector roads
- Clamp s attributes that equal/overflow road length
- Validate paramPoly3 segments (NaN/Inf / extreme curvature); optional repair-to-line

Pure stdlib (xml.etree.ElementTree). Safe to run on Windows/PowerShell.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple, Dict, Any
import xml.etree.ElementTree as ET


EPS = 1e-9
DEFAULT_MAX_CURV = 1.5  # conservative proxy
AUTO_CONN_ID_PREFIX = "auto_conn_"


@dataclass
class Finding:
    code: str
    message: str
    road_id: str | None = None
    extra: Dict[str, Any] | None = None


def _float(x: str | None, default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _remove_degenerate_roadmarks(root: ET.Element, findings: List[Finding]) -> None:
    for rm in root.findall(".//roadMark"):
        rmt = rm.get("type", "")
        if rmt not in ("solid", "broken"):
            continue
        to_delete = []
        for ln in rm.findall("line"):
            length = _float(ln.get("length"), 0.0)
            space = _float(ln.get("space"), 0.0)
            if abs(length) <= EPS and abs(space) <= EPS:
                to_delete.append(ln)
        for ln in to_delete:
            rm.remove(ln)
            findings.append(Finding("ROADMARK_DEGENERATE", "Removed degenerate roadMark line (length=0 space=0)"))


def _zero_laneoffset_on_junctions(root: ET.Element, findings: List[Finding]) -> None:
    for road in root.findall(".//road"):
        rid = road.get("id", "?")
        junction = road.get("junction", "-1")
        if junction is None or junction == "-1":
            continue
        lanes = road.find("lanes")
        if lanes is None:
            continue
        offsets = lanes.findall("laneOffset")
        for lo in offsets:
            lo.set("a", "0.0")
            lo.set("b", "0.0")
            lo.set("c", "0.0")
            lo.set("d", "0.0")
        if not offsets:
            new_lo = ET.Element("laneOffset", {"s": "0.0", "a": "0.0", "b": "0.0", "c": "0.0", "d": "0.0"})
            lanes.insert(0, new_lo)
        findings.append(Finding("LANEOFFSET_JUNCTION_ZEROED", "Zeroed laneOffset on junction road", rid))


def _clamp_s_endpoints(root: ET.Element, findings: List[Finding]) -> None:
    for road in root.findall(".//road"):
        rid = road.get("id", "?")
        length = _float(road.get("length"), 0.0)
        if length <= 0:
            continue
        max_s = max(0.0, length - 1e-3)
        for elem in road.iter():
            if "s" in elem.attrib:
                s_val = _float(elem.get("s"))
                if s_val + EPS >= length:
                    elem.set("s", f"{max_s:.8f}")
                    findings.append(Finding("S_CLAMPED", f"Clamped s from {s_val} to {max_s}", rid))


def _parampoly3_sample(px: float, py: float, pz: float, qx: float, qy: float, p_range: Tuple[float, float], p: float) -> Tuple[float, float]:
    t = p_range[0] + p * (p_range[1] - p_range[0])
    x = px + py * t + pz * t * t + qx * t * t * t
    y = qy  # placeholder, actual paramPoly3 has a/b/c/d for y; below we use full set
    return x, y


def _curv_proxy(xs: List[float], ys: List[float]) -> float:
    # simple finite diff curvature proxy
    if len(xs) < 3:
        return 0.0
    curv = 0.0
    for i in range(1, len(xs) - 1):
        ax = xs[i] - xs[i - 1]
        ay = ys[i] - ys[i - 1]
        bx = xs[i + 1] - xs[i]
        by = ys[i + 1] - ys[i]
        cross = abs(ax * by - ay * bx)
        norm = math.hypot(ax, ay) * math.hypot(bx, by)
        if norm > EPS:
            curv = max(curv, cross / norm)
    return curv


def _parampoly3_check_and_repair(root: ET.Element, repair_to_line: bool, max_curv: float, findings: List[Finding]) -> None:
    for road in root.findall(".//road"):
        rid = road.get("id", "?")
        plan = road.find("planView")
        if plan is None:
            continue
        geoms = plan.findall("geometry")
        for idx, g in enumerate(geoms):
            pp = g.find("paramPoly3")
            if pp is None:
                continue
            length = _float(g.get("length"), 0.0)
            if length <= 0:
                continue
            try:
                a_u = _float(pp.get("aU"))
                b_u = _float(pp.get("bU"))
                c_u = _float(pp.get("cU"))
                d_u = _float(pp.get("dU"))
                a_v = _float(pp.get("aV"))
                b_v = _float(pp.get("bV"))
                c_v = _float(pp.get("cV"))
                d_v = _float(pp.get("dV"))
                p_range = (_float(pp.get("pRange", "0")), 1.0)
            except Exception:
                findings.append(Finding("PARAMPOLY3_PARSE_FAIL", f"Could not parse paramPoly3 in road {rid} geom {idx}", rid))
                continue

            xs: List[float] = []
            ys: List[float] = []
            bad = False
            for p in (0.0, 0.25, 0.5, 0.75, 1.0):
                t = p_range[0] + p * (p_range[1] - p_range[0])
                x = a_u + b_u * t + c_u * t * t + d_u * t * t * t
                y = a_v + b_v * t + c_v * t * t + d_v * t * t * t
                if not (math.isfinite(x) and math.isfinite(y)):
                    bad = True
                    break
                xs.append(x)
                ys.append(y)
            if bad:
                msg = f"NaN/Inf in paramPoly3 (road {rid} geom {idx})"
                if repair_to_line:
                    _repair_parampoly3_to_line(g, findings, rid, idx, msg)
                else:
                    findings.append(Finding("PARAMPOLY3_INVALID", msg, rid))
                continue
            curv = _curv_proxy(xs, ys)
            if curv > max_curv:
                msg = f"paramPoly3 excessive curvature {curv:.3f} (road {rid} geom {idx})"
                if repair_to_line:
                    _repair_parampoly3_to_line(g, findings, rid, idx, msg)
                else:
                    findings.append(Finding("PARAMPOLY3_CURV_EXCEEDED", msg, rid))


def _repair_parampoly3_to_line(geom: ET.Element, findings: List[Finding], rid: str, idx: int, reason: str) -> None:
    # Preserve geometry attributes s, x, y, hdg, length
    attrs = {k: v for k, v in geom.attrib.items()}
    geom.clear()
    geom.tag = "geometry"
    for k, v in attrs.items():
        geom.set(k, v)
    line = ET.Element("line")
    geom.append(line)
    findings.append(Finding("PARAMPOLY3_REPAIRED_TO_LINE", f"{reason} -> replaced with line", rid, {"geometry_index": idx}))


def harden_xodr(
    in_path: Path,
    out_path: Path,
    *,
    fix_roadmarks: bool = True,
    fix_laneoffset_junctions: bool = True,
    clamp_s_endpoints: bool = True,
    parampoly3_sanity: bool = True,
    repair_parampoly3_to_line: bool = False,
    max_curv: float = DEFAULT_MAX_CURV,
    validate_only: bool = False,
    fix_connectivity: bool = True,
    auto_repair_connectivity: bool = True,
    report_path: Path | None = None,
) -> Dict[str, Any]:
    findings: List[Finding] = []
    tree = ET.parse(in_path)
    root = tree.getroot()

    if fix_roadmarks:
        _remove_degenerate_roadmarks(root, findings)
    if fix_laneoffset_junctions:
        _zero_laneoffset_on_junctions(root, findings)
    if clamp_s_endpoints:
        _clamp_s_endpoints(root, findings)
    if parampoly3_sanity:
        _parampoly3_check_and_repair(root, repair_parampoly3_to_line, max_curv, findings)
    if fix_connectivity:
        _fix_connectivity(root, findings, repair=auto_repair_connectivity)

    # ok=False if any INVALID findings exist (unrepaired issues)
    invalid_codes = [f.code for f in findings if "INVALID" in f.code]
    ok = len(invalid_codes) == 0
    repair_count = sum(1 for f in findings if "REMOVED" in f.code or "REPAIRED" in f.code or "ADDED" in f.code or "ZEROED" in f.code or "CLAMPED" in f.code)
    report = {"ok": ok, "findings": [asdict(f) for f in findings], "repair_count": repair_count, "invalid_count": len(invalid_codes)}
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")

    if not validate_only:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        # Ensure trailing newline
        with open(out_path, "r+b") as f:
            f.seek(0, 2)  # end
            if f.tell() > 0:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    f.write(b"\n")
    return report


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="CARLA crash hardener for XODR (Windows-safe).")
    ap.add_argument("--in", dest="inp", required=True, help="Input XODR")
    ap.add_argument("--out", dest="out", required=True, help="Output XODR (hardened)")
    ap.add_argument("--report-json", dest="report_json", help="Optional report JSON path")
    ap.add_argument("--fix-roadmarks", action="store_true", default=True, help="Remove degenerate roadMark lines (default on)")
    ap.add_argument("--no-fix-roadmarks", dest="fix_roadmarks", action="store_false", help="Disable roadMark fix")
    ap.add_argument("--fix-laneoffset-junctions", action="store_true", default=True, help="Zero laneOffset on junction roads (default on)")
    ap.add_argument("--no-fix-laneoffset-junctions", dest="fix_laneoffset_junctions", action="store_false", help="Disable laneOffset junction fix")
    ap.add_argument("--clamp-s-endpoints", action="store_true", default=True, help="Clamp s==road.length endpoints (default on)")
    ap.add_argument("--no-clamp-s-endpoints", dest="clamp_s_endpoints", action="store_false", help="Disable s clamp")
    ap.add_argument("--parampoly3-sanity", action="store_true", default=True, help="Validate paramPoly3 segments (default on)")
    ap.add_argument("--no-parampoly3-sanity", dest="parampoly3_sanity", action="store_false", help="Disable paramPoly3 checks")
    ap.add_argument("--repair-parampoly3-to-line", action="store_true", help="Repair failing paramPoly3 to line")
    ap.add_argument("--max-curv", type=float, default=DEFAULT_MAX_CURV, help="Curvature proxy threshold for paramPoly3")
    ap.add_argument("--validate-only", action="store_true", help="Run checks, write report, do not modify XODR")
    ap.add_argument("--fix-connectivity", action="store_true", default=True, help="Validate/repair lane/road connectivity (default on)")
    ap.add_argument("--no-fix-connectivity", dest="fix_connectivity", action="store_false", help="Disable connectivity repair")
    ap.add_argument("--auto-repair-connectivity", action="store_true", default=True, help="Automatically strip invalid lane/road links (default on). If disabled, report ok=False on bad links.")
    ap.add_argument("--no-auto-repair-connectivity", dest="auto_repair_connectivity", action="store_false", help="Do not auto-repair; only report invalid links.")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    report = harden_xodr(
        Path(args.inp),
        Path(args.out),
        fix_roadmarks=args.fix_roadmarks,
        fix_laneoffset_junctions=args.fix_laneoffset_junctions,
        clamp_s_endpoints=args.clamp_s_endpoints,
        parampoly3_sanity=args.parampoly3_sanity,
        repair_parampoly3_to_line=args.repair_parampoly3_to_line,
        max_curv=args.max_curv,
        validate_only=args.validate_only,
        fix_connectivity=args.fix_connectivity,
        auto_repair_connectivity=args.auto_repair_connectivity,
        report_path=Path(args.report_json) if args.report_json else None,
    )
    return 0


def _lane_sections_sorted(road: ET.Element) -> List[ET.Element]:
    lanes = road.find("lanes")
    if lanes is None:
        return []
    lss = list(lanes.findall("laneSection"))
    lss.sort(key=lambda e: _float(e.get("s"), 0.0))
    return lss


def _lanes_at_contact(road: ET.Element, contact: str) -> Dict[int, ET.Element]:
    lss = _lane_sections_sorted(road)
    if not lss:
        return {}
    ls = lss[0] if contact == "start" else lss[-1]
    lanes: Dict[int, ET.Element] = {}
    for side in ("left", "center", "right"):
        part = ls.find(side)
        if part is None:
            continue
        for ln in part.findall("lane"):
            try:
                lid = int(ln.get("id", "0"))
                lanes[lid] = ln
            except Exception:
                continue
    return lanes


def _validate_junction_connector(root: ET.Element, road: ET.Element, rid: str, findings: List[Finding], repair: bool) -> None:
    """Validate that junction connector road appears in its junction's connections."""
    j_id = road.get("junction")
    if j_id in (None, "-1"):
        return
    j = root.find(f".//junction[@id='{j_id}']")
    if j is None:
        findings.append(Finding("JUNCTION_MISSING", f"Junction {j_id} not found for connector road", rid))
        return
    existing = j.findall(f"connection[@connectingRoad='{rid}']")
    if existing:
        return
    # Missing connection
    if repair:
        conn_id = AUTO_CONN_ID_PREFIX + str(rid)
        conn = ET.Element("connection", {"id": conn_id, "incomingRoad": "-1", "connectingRoad": rid, "contactPoint": "start"})
        ll = ET.Element("laneLink", {"from": "-1", "to": "-1"})
        conn.append(ll)
        j.append(conn)
        findings.append(Finding("JUNCTION_CONN_ADDED", "Added missing junction connection for connector road", rid))
    else:
        findings.append(Finding("JUNCTION_CONN_INVALID", f"Connector road not listed in junction {j_id}", rid))


def _fix_connectivity(root: ET.Element, findings: List[Finding], repair: bool = True) -> None:
    """Validate and optionally repair road/lane connectivity.

    If repair=False: only emit INVALID findings, do NOT mutate XML.
    If repair=True: remove invalid links/elements, emit REMOVED findings.
    """
    roads = {r.get("id", ""): r for r in root.findall(".//road")}

    # Junction connectors: validate they appear in junction connections
    for rid, road in roads.items():
        junction = road.get("junction", "-1")
        if junction is not None and junction != "-1":
            _validate_junction_connector(root, road, rid, findings, repair)
            # Junction connectors should not have road-level links
            link = road.find("link")
            if link is not None:
                if repair:
                    road.remove(link)
                    findings.append(Finding("JUNCTION_LINK_REMOVED", "Removed road.link on junction connector", rid))
                else:
                    findings.append(Finding("JUNCTION_LINK_INVALID", "Junction connector has road.link (should not)", rid))

    # Road-level link validation (target road existence)
    for rid, road in roads.items():
        if road.get("junction", "-1") not in (None, "-1"):
            continue  # already handled above
        link = road.find("link")
        if link is None:
            continue
        for tag in ("predecessor", "successor"):
            el = link.find(tag)
            if el is None:
                continue
            el_type = el.get("elementType", "road")
            rref = el.get("elementId")
            if el_type == "road" and rref and rref not in roads:
                if repair:
                    link.remove(el)
                    findings.append(Finding("ROAD_LINK_REMOVED", f"Removed {tag} to missing road {rref}", rid))
                else:
                    findings.append(Finding("ROAD_LINK_INVALID", f"{tag} points to missing road {rref}", rid))

    # Lane successor/predecessor validation
    for rid, road in roads.items():
        link = road.find("link")
        succ_ref = None
        pred_ref = None
        succ_contact = "start"
        pred_contact = "end"
        if link is not None:
            succ = link.find("successor")
            pred = link.find("predecessor")
            if succ is not None:
                succ_ref = succ.get("elementId")
                succ_contact = succ.get("contactPoint", "start")
            if pred is not None:
                pred_ref = pred.get("elementId")
                pred_contact = pred.get("contactPoint", "end")
        target_info = {
            "successor": (succ_ref, succ_contact),
            "predecessor": (pred_ref, pred_contact),
        }

        lss = _lane_sections_sorted(road)
        if not lss:
            continue
        first_ls = lss[0]
        last_ls = lss[-1]

        for direction, (rref, contact_point) in target_info.items():
            if not rref or rref not in roads:
                continue
            target = roads[rref]
            t_lanes = _lanes_at_contact(target, contact_point)
            # Check lanes at start (predecessor) or end (successor) of current road
            ls = first_ls if direction == "predecessor" else last_ls

            for side in ("left", "center", "right"):
                part = ls.find(side)
                if part is None:
                    continue
                for ln in part.findall("lane"):
                    lane_id = ln.get("id", "0")
                    # Check lane link element
                    lane_link = ln.find("link")
                    if lane_link is None:
                        continue
                    link_el = lane_link.find(direction)
                    if link_el is None:
                        continue
                    val = link_el.get("id")
                    if val is None:
                        continue
                    try:
                        lid = int(val)
                    except Exception:
                        if repair:
                            lane_link.remove(link_el)
                            findings.append(Finding("LANE_LINK_REMOVED", f"Removed non-integer lane {direction}", rid))
                        else:
                            findings.append(Finding("LANE_LINK_INVALID", f"Non-integer lane {direction} id", rid))
                        continue
                    if lid not in t_lanes:
                        if repair:
                            lane_link.remove(link_el)
                            findings.append(Finding("LANE_LINK_REMOVED", f"Removed lane {direction} to missing lane {lid} on road {rref}", rid))
                        else:
                            findings.append(Finding("LANE_LINK_INVALID", f"Lane {lane_id} {direction} points to missing lane {lid} on road {rref}", rid))



if __name__ == "__main__":
    raise SystemExit(main())
