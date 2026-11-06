#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Connector boundary elevation reconciliation (source-stage, Lane Z).

Every junction connector whose reference-line z at a contact boundary does
not match the incident road's boundary z (measured exactly the way the P0
oracle's ``scan_connector_lane_interface_dz`` measures it) is re-profiled as
a cubic Hermite segment instantiated from the boundary conditions of the
roads it connects:

    z(0)   = z of incident road 1 at its junction-facing boundary
    z'(0)  = grade of incident road 1 at that boundary
    z(L)   = z of incident road 2 at its junction-facing boundary
    z'(L)  = grade of incident road 2 at that boundary

so that both interface seams become exactly C0 (dz == 0) and grade
continuity is inherited instead of invented. The reconciler repairs the
CONNECTOR only -- incident roads, lane topology and planView are never
touched. This runs inside the generation pipeline at source stage; it is
never applied as a post-hoc mutation of a promoted artifact.

Anchoring precedence, per connector side:
  1. ``<connection contactPoint=...>`` records naming this connector: the
     incident road's junction-facing boundary (resolved from the incident
     road's own <link> predecessor/successor; falls back to the oracle
     convention "incoming end" only when the links do not name the junction).
  2. The connector's road-level successor road (elementType != junction),
     resolved to its junction-facing boundary (start-facing by construction
     of the link chain, matching the oracle's outgoing convention).

Connectors whose seam dz is already within threshold on both sides are left
untouched (minimal mutation). Connectors with one-sided or conflicting
boundary candidates are skipped and reported (fail-closed: the P0-C oracle
measure after regeneration decides admission, never this report alone).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["reconcile_connector_elevations", "evaluate_profile_at", "hermite_coefficients"]

DZ_THRESHOLD_M = 0.5  # mirrors the P0-C oracle / audit interface threshold


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _length_of(road: ET.Element) -> float:
    geoms = road.findall("./planView/geometry")
    if not geoms:
        return 0.0
    last = geoms[-1]
    return _f(last.get("s")) + _f(last.get("length"))


def evaluate_profile_at(road: ET.Element, at_start: bool) -> Optional[Tuple[float, float]]:
    """Reference-line z and true grade d/ds z at a road boundary.

    Returns ``(z, grade)`` or ``None`` when the road carries no usable
    elevationProfile. ``grade`` is the segment derivative evaluated at the
    boundary (b + 2c*ds + 3d*ds^2), which reduces to the segment's ``b`` for
    the flat/linear profiles this pipeline writes.
    """
    profile = road.find("elevationProfile")
    if profile is None:
        return None
    segments = [(_f(e.get("s")), e) for e in profile.findall("elevation")]
    if not segments:
        return None
    segments.sort(key=lambda t: t[0])
    s_target = 0.0 if at_start else _length_of(road)
    s0, el = segments[0]
    for cand in segments:
        if cand[0] <= s_target:
            s0, el = cand
        else:
            break
    a = _f(el.get("a"))
    b = _f(el.get("b"))
    c = _f(el.get("c"))
    d = _f(el.get("d"))
    ds = max(0.0, s_target - s0)
    z = a + b * ds + c * ds * ds + d * ds ** 3
    grade = b + 2.0 * c * ds + 3.0 * d * ds * ds
    return z, grade


def hermite_coefficients(
    z0: float, g0: float, z1: float, g1: float, length: float
) -> Tuple[float, float, float, float]:
    """Cubic z(s) = a + b s + c s^2 + d s^3 with prescribed boundary z/grade.

    Satisfies z(0)=z0, z'(0)=g0, z(L)=z1, z'(L)=g1 exactly.
    """
    if length <= 0.0:
        return z0, 0.0, 0.0, 0.0
    delta = z1 - z0
    b0 = g0
    d3 = (g1 - g0) / (length * length) - 2.0 * (delta - g0 * length) / (length ** 3)
    c2 = (delta - b0 * length - d3 * length ** 3) / (length ** 2)
    return z0, b0, c2, d3


def _junction_side_of(road: ET.Element, junction_id: str) -> str:
    '''"start"/"end"/"not_linked": which road boundary faces the junction.'''
    links = road.find("link")
    if links is None:
        return "not_linked"
    pred = links.find("predecessor")
    succ = links.find("successor")
    if (
        pred is not None
        and pred.get("elementType") == "junction"
        and pred.get("elementId") == junction_id
    ):
        return "start"
    if (
        succ is not None
        and succ.get("elementType") == "junction"
        and succ.get("elementId") == junction_id
    ):
        return "end"
    return "not_linked"


def _boundary_conditions(road: ET.Element, side: str) -> Optional[Tuple[float, float]]:
    ev = evaluate_profile_at(road, side != "end")
    return ev


def _replace_profile(
    road: ET.Element, a: float, b: float, c: float, d: float
) -> None:
    """Replace the road's elevationProfile with a single cubic segment.

    When the road has no elevationProfile element yet, one is created
    directly after <planView> (ASAM OpenDRIVE xs:sequence order for <road>
    children).
    """
    profile = road.find("elevationProfile")
    if profile is None:
        plan = road.find("planView")
        profile = ET.Element("elevationProfile")
        if plan is None:
            road.insert(0, profile)
        else:
            road.insert(list(road).index(plan) + 1, profile)
    for existing in list(profile.findall("elevation")):
        profile.remove(existing)
    ET.SubElement(
        profile,
        "elevation",
        {
            "s": "0.0",
            "a": f"{a:.6f}",
            "b": f"{b:.9f}",
            "c": f"{c:.12f}",
            "d": f"{d:.15f}",
        },
    )


def reconcile_connector_elevations(
    root: ET.Element,
    *,
    dz_threshold_m: float = DZ_THRESHOLD_M,
    max_examples: int = 25,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "schema": "connector_elevation_reconciler_v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "dz_threshold_m": float(dz_threshold_m),
        "connectors_seen": 0,
        "already_continuous": 0,
        "rewritten": 0,
        "missing_boundary_conditions": 0,
        "conflicting_boundary_conditions": 0,
        "max_abs_dz_after": 0.0,
        "worst_after": None,
        "examples": [],
        "skipped_records": [],
    }
    roads_by_id: Dict[str, ET.Element] = {
        str(r.get("id") or "").strip(): r
        for r in root.findall("road")
        if str(r.get("id") or "").strip()
    }

    # connector_id -> side -> list of (z, grade, source) boundary candidates
    side_candidates: Dict[str, Dict[str, List[Tuple[float, float, str]]]] = {}
    for junction in root.findall("junction"):
        junction_id = str(junction.get("id") or "").strip()
        if not junction_id:
            continue
        for conn in junction.findall("connection"):
            incoming_id = str(conn.get("incomingRoad") or "").strip()
            connector_id = str(conn.get("connectingRoad") or "").strip()
            if not incoming_id or not connector_id:
                continue
            incoming = roads_by_id.get(incoming_id)
            connector = roads_by_id.get(connector_id)
            if incoming is None or connector is None:
                continue
            side_on_connector = "end" if conn.get("contactPoint") == "end" else "start"
            inc_side = _junction_side_of(incoming, junction_id)
            if inc_side == "not_linked":
                # oracle convention fallback: incoming road boundary is its end
                inc_side = "end"
            bc = _boundary_conditions(incoming, inc_side)
            if bc is None:
                report["skipped_records"].append(
                    {
                        "connector_road": connector_id,
                        "junction_id": junction_id,
                        "reason": "incident_profile_missing",
                        "incident_road": incoming_id,
                        "side": side_on_connector,
                    }
                )
                continue
            side_candidates.setdefault(connector_id, {"start": [], "end": []})
            side_candidates[connector_id][side_on_connector].append(
                (bc[0], bc[1], f"connection:{junction_id}:{incoming_id}")
            )

    def _finalize_connector(connector_id: str, sides: Dict[str, List[Tuple[float, float, str]]]) -> None:
        connector = roads_by_id.get(connector_id)
        if connector is None:
            return
        report["connectors_seen"] += 1

        # outgoing-road anchor for the end side (oracle convention: outgoing
        # start boundary) when no connection record supplied a candidate.
        if not sides["end"]:
            succ = connector.find("./link/successor")
            if succ is not None and succ.get("elementType") != "junction":
                outgoing = roads_by_id.get(str(succ.get("elementId") or "").strip())
                if outgoing is not None:
                    out_junction_id = str(succ.get("elementId") or "").strip()
                    out_side = _junction_side_of(outgoing, out_junction_id)
                    bc = _boundary_conditions(
                        outgoing, out_side if out_side != "not_linked" else "start"
                    )
                    if bc is not None:
                        sides["end"].append((bc[0], bc[1], f"successor:{out_junction_id}"))

        chosen: Dict[str, Tuple[float, float]] = {}
        conflicts: List[str] = []
        for side, cands in sides.items():
            if not cands:
                continue
            zs = [round(x[0], 3) for x in cands]
            if max(zs) - min(zs) > 1.0:
                conflicts.append(
                    f"{side}:{[(round(v[0], 3), v[2]) for v in cands]}"[:200]
                )
                continue
            mid = sorted(cands, key=lambda t: t[0])[len(cands) // 2]
            chosen[side] = (mid[0], mid[1])
        if conflicts:
            report["conflicting_boundary_conditions"] += 1
            report["skipped_records"].append(
                {
                    "connector_road": connector_id,
                    "reason": "conflicting_boundary_candidates",
                    "detail": "; ".join(conflicts)[:300],
                }
            )
            return
        if len(chosen) < 2:
            report["missing_boundary_conditions"] += 1
            report["skipped_records"].append(
                {
                    "connector_road": connector_id,
                    "reason": "missing_boundary_condition",
                    "sides_present": sorted(chosen),
                }
            )
            return

        ev_start = evaluate_profile_at(connector, True)
        ev_end = evaluate_profile_at(connector, False)
        dz_start = None if ev_start is None else round(chosen["start"][0] - ev_start[0], 4)
        dz_end = None if ev_end is None else round(chosen["end"][0] - ev_end[0], 4)
        worst_before: Optional[float] = None
        if ev_start is not None and ev_end is not None:
            worst_before = max(abs(dz_start), abs(dz_end))

        if worst_before is not None and worst_before <= dz_threshold_m:
            report["already_continuous"] += 1
            return

        length = _length_of(connector)
        a, b, c, d = hermite_coefficients(
            chosen["start"][0],
            chosen["start"][1],
            chosen["end"][0],
            chosen["end"][1],
            length,
        )
        _replace_profile(connector, a, b, c, d)
        report["rewritten"] += 1

        # immediate closed-loop verification: the written segment must
        # reproduce both boundary conditions exactly.
        ev_start_after = evaluate_profile_at(connector, True)
        ev_end_after = evaluate_profile_at(connector, False)
        dz_after_start = abs(chosen["start"][0] - ev_start_after[0]) if ev_start_after else None
        dz_after_end = abs(chosen["end"][0] - ev_end_after[0]) if ev_end_after else None
        if (dz_after_start or 0.0) > 1e-3 or (dz_after_end or 0.0) > 1e-3:
            report["skipped_records"].append(
                {
                    "connector_road": connector_id,
                    "reason": "post_write_verification_failed",
                    "dz_after_start": dz_after_start,
                    "dz_after_end": dz_after_end,
                }
            )
        if len(report["examples"]) < max_examples:
            report["examples"].append(
                {
                    "connector_road": connector_id,
                    "dz_before_start": dz_start,
                    "dz_before_end": dz_end,
                    "dz_after_start": round(dz_after_start, 6) if dz_after_start is not None else None,
                    "dz_after_end": round(dz_after_end, 6) if dz_after_end is not None else None,
                    "length_m": round(length, 3),
                    "coefficients": {
                        "a": round(a, 6),
                        "b": round(b, 9),
                        "c": round(c, 12),
                        "d": round(d, 15),
                    },
                }
            )

    for connector_id in sorted(side_candidates):
        _finalize_connector(connector_id, side_candidates[connector_id])

    worst = 0.0
    worst_rec = None
    for ex in report["examples"]:
        for key in ("dz_after_start", "dz_after_end"):
            v = ex.get(key)
            if v is not None and v > worst:
                worst = v
                worst_rec = {"connector_road": ex["connector_road"], key: v}
    report["max_abs_dz_after"] = worst
    report["worst_after"] = worst_rec
    return report


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Reconcile connector boundary elevations")
    ap.add_argument("--xodr", required=True, help="input XODR (copied+repaired tree, never in-place)")
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    tree = ET.parse(args.xodr)
    inner_root = tree.getroot()
    rep = reconcile_connector_elevations(inner_root)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2)
    print(
        f"connectors={rep['connectors_seen']} rewritten={rep['rewritten']} "
        f"already_continuous={rep['already_continuous']} "
        f"missing_bc={rep['missing_boundary_conditions']} "
        f"conflicts={rep['conflicting_boundary_conditions']}"
    )
