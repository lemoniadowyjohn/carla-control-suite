"""GAP-026 severe-angle closure: narrow per-connector tangent repair.

Repairs ONLY junction connector roads whose reference-line interface
heading violates the GAP026 angle criterion (>12 deg) and whose
source-backed endpoint/tangent anchors are proven.

Method: single normalized-``pRange`` ``<paramPoly3>`` cubic Hermite segment
through (start position, start tangent) -> (end position, end tangent),
evaluated in a local frame (origin = start point, x-axis = start tangent).
Hermite interpolation satisfies all four boundary conditions exactly, which
neither start-heading rotation (breaks end continuity) nor single circular
arcs (cannot meet both tangents in general) can do.

Scope discipline (CARLA-CLOSURE-17):
- generator geometry repair at source stage, before geometry freeze
- no threshold, checker, oracle, or Stage-8 changes
- no laneLink / connection / road-link identity changes
- no generalized geometry framework; lane topology untouched
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.geometry.opendrive_geometry_kernel import (
    endpoint as _kernel_endpoint,
    pose_at_s as _kernel_pose_at_s,
)
from ultimate_pipeline.topology.junction_connector_rebuild import (
    _find_incoming_anchor,
    _find_outgoing_anchor,
    _road_endpoints,
)

ANGLE_THRESHOLD_RAD = math.radians(12.0)
ALIGNED_GAP_M = 0.5
POS_TOL_M = 1e-4
HDG_TOL_RAD = 1e-4
MIN_CONNECTOR_LENGTH_M = 1e-3


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    if math.isnan(out) or math.isinf(out):
        return float(default)
    return out


def _norm_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _angle_error(a: float, b: float) -> float:
    return abs(_norm_angle(float(a) - float(b)))


def _sorted_geometries(road: ET.Element) -> List[ET.Element]:
    geoms = list(road.findall("./planView/geometry"))
    geoms.sort(key=lambda g: _safe_float(g.get("s"), 0.0))
    return geoms


def _is_connector_road(road: Optional[ET.Element]) -> bool:
    if road is None:
        return False
    return str(road.get("junction") or "").strip() not in ("", "-1")


def _hermite_coefficients(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    m0: float,
    t1x: float,
    t1y: float,
) -> Tuple[float, float, float, float, float, float, float, float]:
    """Normalized cubic Hermite coefficients in the local frame.

    P0=(0,0) with unit-x tangent scaled by m0; P1=(U,V) with tangent
    (T1x,T1y). Returns (aU,bU,cU,dU,aV,bV,cV,dV) with aU=aV=0, bU=m0,
    bV=0 by construction.
    """
    ux, uy = p0
    vx, vy = p1
    u = vx - ux
    v = vy - uy
    au, av = 0.0, 0.0
    bu, bv = float(m0), 0.0
    cu = 3.0 * u - 2.0 * m0 - t1x
    du = -2.0 * u + m0 + t1x
    cv = 3.0 * v - t1y
    dv = -2.0 * v + t1y
    return au, bu, cu, du, av, bv, cv, dv


def _eval_hermite(
    coeffs: Tuple[float, float, float, float, float, float, float, float],
    p: float,
) -> Tuple[float, float]:
    _, bu, cu, du, _, bv, cv, dv = coeffs
    # aU=aV=0
    u = bu * p + cu * p * p + du * p * p * p
    v = bv * p + cv * p * p + dv * p * p * p
    return u, v


def _hermite_end_tangent_ok(
    coeffs: Tuple[float, float, float, float, float, float, float, float],
    want_hdg_local: float,
) -> bool:
    _, bu, cu, du, _, bv, cv, dv = coeffs
    # derivative at p=1: U'(1) = bU + 2cU + 3dU ; V'(1) = bV + 2cV + 3dV
    du1 = bu + 2.0 * cu + 3.0 * du
    dv1 = bv + 2.0 * cv + 3.0 * dv
    if abs(du1) < 1e-12 and abs(dv1) < 1e-12:
        return False
    got = math.atan2(dv1, du1)
    return _angle_error(got, want_hdg_local) <= HDG_TOL_RAD


def _sampled_length(
    x0: float, y0: float, hdg0: float, coeffs: Tuple[float, float, float, float, float, float, float, float], n: int = 64
) -> float:
    ch, sh = math.cos(hdg0), math.sin(hdg0)
    prev = (x0, y0)
    total = 0.0
    for i in range(1, n + 1):
        u, v = _eval_hermite(coeffs, i / n)
        x = x0 + u * ch - v * sh
        y = y0 + u * sh + v * ch
        total += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
    return total


@dataclass
class TangentFitResult:
    connectors_examined: int = 0
    attempted: int = 0
    rebuilt: int = 0
    rejected: int = 0
    skipped_valid: int = 0
    skipped_no_anchor: int = 0
    skipped_not_connector: int = 0
    rejections: List[Dict[str, Any]] = field(default_factory=list)
    examples: List[Dict[str, Any]] = field(default_factory=list)


def _lane_sections_in_bounds(road: ET.Element, length: float) -> bool:
    for sec in road.findall("./lanes/laneSection"):
        try:
            s = float(sec.get("s", "0") or 0.0)
        except Exception:
            return False
        if not math.isfinite(s) or s < -1e-9 or s > length + 1e-6:
            return False
    return True


def _topology_identity_snapshot(root: ET.Element) -> Tuple[int, int, int]:
    n_conn = sum(len(j.findall("connection")) for j in root.findall("junction"))
    n_ll = sum(len(c.findall("laneLink")) for j in root.findall("junction") for c in j.findall("connection"))
    n_roadlinks = 0
    for r in root.findall("road"):
        link = r.find("link")
        if link is None:
            continue
        n_roadlinks += len(link.findall("successor")) + len(link.findall("predecessor"))
    return n_conn, n_ll, n_roadlinks


def apply_junction_connector_tangent_fit(
    root: ET.Element,
    *,
    angle_threshold_rad: float = ANGLE_THRESHOLD_RAD,
    aligned_gap_m: float = ALIGNED_GAP_M,
    max_examples: int = 25,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Repair severe-angle junction connectors via normalized Hermite fit.

    For each junction connection whose connector road start interface angle
    error exceeds ``angle_threshold_rad``: resolve source-backed incoming
    and outgoing anchors; rebuild the connector planView as one normalized
    paramPoly3 Hermite segment; accept only if per-connector validation
    passes (endpoint positions/tangents, finite coefficients, road length
    consistent, laneSection bounds, topology identity unchanged).
    """
    result = TangentFitResult()
    roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}

    junctions = sorted(root.findall("junction"), key=lambda j: str(j.get("id") or ""))
    for junction in junctions:
        jid = str(junction.get("id") or "")
        connections = sorted(
            junction.findall("connection"),
            key=lambda c: (
                str(c.get("connectingRoad") or ""),
                str(c.get("incomingRoad") or ""),
                str(c.get("id") or ""),
            ),
        )
        for conn in connections:
            incoming_id = str(conn.get("incomingRoad") or "")
            connector_id = str(conn.get("connectingRoad") or "")
            contact = str(conn.get("contactPoint") or "start").strip()
            if contact not in ("start", "end"):
                continue
            incoming = roads.get(incoming_id)
            connector = roads.get(connector_id)
            if incoming is None or connector is None:
                result.skipped_no_anchor += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id,
                    "reason": "missing_incoming_or_connector_road",
                })
                continue
            if not _is_connector_road(connector):
                result.skipped_not_connector += 1
                continue
            result.connectors_examined += 1

            eps = _road_endpoints(connector)
            inceps = _road_endpoints(incoming)
            if eps is None or inceps is None:
                result.skipped_no_anchor += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "missing_planview_pose",
                })
                continue

            # Current interface angle at the junction attach side.
            if contact == "start":
                cur_pose = eps["start"]
                # incoming junction-side end: prefer declared successor link
                in_anchor, _src = _find_incoming_anchor(
                    junction_id=jid, incoming_road=incoming,
                    connector_attach_pose=cur_pose)
            else:
                cur_pose = eps["end"]
                in_anchor, _src = _find_incoming_anchor(
                    junction_id=jid, incoming_road=incoming,
                    connector_attach_pose=cur_pose)
            if in_anchor is None:
                result.skipped_no_anchor += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "missing_incoming_anchor",
                })
                continue
            if _angle_error(cur_pose.hdg, in_anchor.hdg) <= float(angle_threshold_rad):
                result.skipped_valid += 1
                continue

            # Outgoing anchor for the far end.
            far = eps["end"] if contact == "start" else eps["start"]
            out_anchor, out_src, _out_id = _find_outgoing_anchor(
                roads_by_id=roads, incoming_id=incoming_id,
                connector_road=connector, connector_contact_point=contact,
                connector_opposite_pose=far)
            if out_anchor is None:
                result.skipped_no_anchor += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "missing_outgoing_anchor:" + str(out_src),
                })
                continue

            # Position policy (SPLIT by gap class).
            start_gap = math.hypot(cur_pose.x - in_anchor.x, cur_pose.y - in_anchor.y)
            if start_gap <= float(aligned_gap_m):
                plan_start = (float(cur_pose.x), float(cur_pose.y))
            else:
                plan_start = (float(in_anchor.x), float(in_anchor.y))
            if contact == "start":
                plan_end = (float(out_anchor.x), float(out_anchor.y))
            else:
                plan_end = (float(out_anchor.x), float(out_anchor.y))

            start_hdg = float(in_anchor.hdg)
            # End tangent from outgoing anchor heading.
            end_hdg = float(out_anchor.hdg)

            # Local frame: origin=plan_start, x-axis=start_hdg.
            dx = plan_end[0] - plan_start[0]
            dy = plan_end[1] - plan_start[1]
            chord = math.hypot(dx, dy)
            if chord < MIN_CONNECTOR_LENGTH_M or not math.isfinite(chord):
                result.rejected += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "degenerate_chord",
                })
                continue
            ch, sh = math.cos(start_hdg), math.sin(start_hdg)
            u = ch * dx + sh * dy
            v = -sh * dx + ch * dy
            m0 = chord
            m1 = chord
            delta = _norm_angle(end_hdg - start_hdg)
            t1x = m1 * math.cos(delta)
            t1y = m1 * math.sin(delta)
            coeffs = _hermite_coefficients((0.0, 0.0), (u, v), m0, t1x, t1y)
            if any(not math.isfinite(c) for c in coeffs):
                result.rejected += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "nonfinite_coefficients",
                })
                continue
            if not _hermite_end_tangent_ok(coeffs, math.atan2(t1y, t1x)):
                result.rejected += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "end_tangent_mismatch",
                })
                continue

            result.attempted += 1
            # Snapshot identity + geometry for atomic revert.
            n_conn_b, n_ll_b, n_rl_b = _topology_identity_snapshot(root)
            old_length = connector.get("length")
            old_plan = connector.find("planView")
            old_plan_index = list(connector).index(old_plan) if old_plan is not None else None
            old_plan_copy = ET.fromstring(ET.tostring(old_plan)) if old_plan is not None else None

            # Write single normalized paramPoly3.
            plan = connector.find("planView")
            if plan is None:
                plan = ET.SubElement(connector, "planView")
            plan.clear()
            geom = ET.SubElement(plan, "geometry", {
                "s": "0.000000000000",
                "x": f"{plan_start[0]:.12f}",
                "y": f"{plan_start[1]:.12f}",
                "hdg": f"{_norm_angle(start_hdg):.12f}",
                "length": "0.000000000000",  # set below after sampling
            })
            au, bu, cu, du, av, bv, cv, dv = coeffs
            ET.SubElement(geom, "paramPoly3", {
                "aU": f"{au:.12f}", "bU": f"{bu:.12f}", "cU": f"{cu:.12f}", "dU": f"{du:.12f}",
                "aV": f"{av:.12f}", "bV": f"{bv:.12f}", "cV": f"{cv:.12f}", "dV": f"{dv:.12f}",
                "pRange": "normalized",
            })
            sampled = _sampled_length(plan_start[0], plan_start[1], start_hdg, coeffs)
            if not math.isfinite(sampled) or sampled <= 0:
                # revert
                _restore(connector, old_length, old_plan_copy, old_plan_index)
                result.rejected += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": "invalid_sampled_length",
                })
                continue
            geom.set("length", f"{sampled:.12f}")
            connector.set("length", f"{sampled:.12f}")

            # Validate via kernel: start/end poses + laneSection bounds + identity.
            ok = True
            reason = ""
            try:
                gs = _sorted_geometries(connector)
                if len(gs) != 1:
                    ok, reason = False, "geometry_count"
                else:
                    ps = _kernel_pose_at_s(gs[0], 0.0)
                    pe = _kernel_endpoint(gs[0])
                    if math.hypot(ps.x - plan_start[0], ps.y - plan_start[1]) > POS_TOL_M:
                        ok, reason = False, "start_position"
                    elif math.hypot(pe.x - plan_end[0], pe.y - plan_end[1]) > POS_TOL_M:
                        ok, reason = False, "end_position"
                    elif _angle_error(ps.heading, start_hdg) > HDG_TOL_RAD:
                        ok, reason = False, "start_heading"
                    elif _angle_error(pe.heading, end_hdg) > HDG_TOL_RAD:
                        ok, reason = False, "end_heading"
                    elif not _lane_sections_in_bounds(connector, sampled):
                        ok, reason = False, "lanesection_bounds"
                    elif _topology_identity_snapshot(root) != (n_conn_b, n_ll_b, n_rl_b):
                        ok, reason = False, "topology_identity"
            except Exception as exc:
                ok, reason = False, "validator_exception:" + str(exc)[:80]
            if not ok:
                _restore(connector, old_length, old_plan_copy, old_plan_index)
                result.rejected += 1
                result.rejections.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id, "reason": reason,
                })
                continue
            result.rebuilt += 1
            if len(result.examples) < max_examples:
                result.examples.append({
                    "junction_id": jid, "connection_id": conn.get("id"),
                    "connecting_road": connector_id,
                    "start_gap_before": round(start_gap, 3),
                })

    return {
        "connectors_examined": result.connectors_examined,
        "attempted": result.attempted,
        "rebuilt": result.rebuilt,
        "rejected": result.rejected,
        "skipped_valid": result.skipped_valid,
        "skipped_no_anchor": result.skipped_no_anchor,
        "skipped_not_connector": result.skipped_not_connector,
        "rejections": result.rejections,
        "examples": result.examples,
    }


def _restore(connector_road, old_length, old_plan_copy, old_plan_index):
    if old_length is None:
        connector_road.attrib.pop("length", None)
    else:
        connector_road.set("length", old_length)
    current = connector_road.find("planView")
    if current is not None:
        connector_road.remove(current)
    if old_plan_copy is not None:
        idx = old_plan_index if old_plan_index is not None else len(list(connector_road))
        connector_road.insert(max(0, min(idx, len(list(connector_road)))), old_plan_copy)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Narrow per-connector Hermite tangent repair (GAP-026 severe-angle).")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)
    tree = ET.parse(args.input)
    root = tree.getroot()
    report = apply_junction_connector_tangent_fit(root)
    tree.write(args.output, encoding="unicode", xml_declaration=True)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k in (
        "connectors_examined", "attempted", "rebuilt", "rejected",
        "skipped_valid", "skipped_no_anchor")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
