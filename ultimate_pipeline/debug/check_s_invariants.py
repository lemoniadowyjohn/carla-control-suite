#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ultimate_pipeline.debug.check_s_invariants

Offline scan (and optional fix) for CARLA-importer-sensitive `s` invariants.

CARLA can crash natively on:
- s < 0 in geometry / elevation / superelevation / laneOffset
- non-monotonic geometry s within a road
- first geometry s != 0
- road length < max(end_s)

This module does not import carla.
"""

from __future__ import annotations

import argparse
import json
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

# Single source of truth for the road-length invariant tolerance.
#
# This MUST match run_n_certify._length_invariant_evidence's tolerance
# (1e-9), which is itself derived from CARLA's mesh-builder assert:
# `s + geometry.length > road.length + 1e-9` crashes the cook. Reporting a
# "0" here with a looser tolerance (the old value was 1e-6, and measured
# only the geometry START s rather than s + length) could hide genuine
# sub-1e-6 length-invariant violations that the certifier -- and CARLA's own
# assert -- would still catch. See also
# ultimate_pipeline.tools.crash_safe_length_repair.TOL_M (same value).
LENGTH_INVARIANT_TOL_M = 1e-9


def scan_s_invariants(xodr_path: str) -> Dict[str, Any]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()

    issues: List[Dict[str, Any]] = []

    def add(road_id: str, kind: str, s_val: float, detail: str) -> None:
        issues.append({
            "road_id": road_id,
            "kind": kind,
            "s": s_val,
            "detail": detail,
        })

    for road in root.findall(".//road"):
        rid = road.get("id", "?")
        rlen = float(road.get("length", "0") or 0.0)

        # planView geometries
        geoms = road.findall("./planView/geometry")
        s_list: List[float] = []
        max_geom_end: float = 0.0
        have_geom_end = False
        for g in geoms:
            s = g.get("s")
            if s is None:
                continue
            try:
                sv = float(s)
            except Exception:
                continue
            s_list.append(sv)
            if sv < 0:
                add(rid, "neg_s_geometry", sv, "planView/geometry")

            glen_raw = g.get("length")
            try:
                glen = float(glen_raw) if glen_raw is not None else 0.0
            except Exception:
                glen = 0.0
            geom_end = sv + glen
            if not have_geom_end or geom_end > max_geom_end:
                max_geom_end = geom_end
                have_geom_end = True

        if s_list:
            if s_list[0] != 0.0:
                add(rid, "first_geom_s_not_zero", s_list[0], "first planView/geometry s")

            for a, b in zip(s_list, s_list[1:]):
                if b < a:
                    add(rid, "non_monotonic_geometry_s", b, f"geometry s decreased ({a} -> {b})")

            # Length invariant: compare the declared road length against the
            # FURTHEST geometry END (s + geometry.length), not just the
            # furthest geometry START s. A geometry can start well inside
            # the declared length yet still extend past it once its own
            # length is added -- that violation is invisible if only
            # max(s_list) is checked. Uses the same tolerance as the
            # certifier (LENGTH_INVARIANT_TOL_M == 1e-9) so a "0" here can
            # never hide a sub-1e-6 violation the certifier would still flag.
            if have_geom_end and max_geom_end > rlen + LENGTH_INVARIANT_TOL_M:
                add(
                    rid,
                    "geom_s_exceeds_road_length",
                    max_geom_end,
                    f"max geom end (s+length)={max_geom_end} > road length={rlen}",
                )

        # laneOffset / elevation / superelevation
        for tag, xp in [
            ("neg_s_laneOffset", "./lanes/laneOffset"),
            ("neg_s_elevation", "./elevationProfile/elevation"),
            ("neg_s_superelevation", "./lateralProfile/superelevation"),
        ]:
            for e in road.findall(xp):
                s = e.get("s")
                if s is None:
                    continue
                try:
                    sv = float(s)
                except Exception:
                    continue
                if sv < 0:
                    add(rid, tag, sv, xp)

    return {"xodr": xodr_path, "issue_count": len(issues), "issues": issues}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xodr", help="Path to .xodr")
    ap.add_argument("--json_out", default=None)
    args = ap.parse_args()

    rep = scan_s_invariants(args.xodr)
    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
    print(f"S_INVARIANTS issues={rep['issue_count']}  json_out={args.json_out or '-'}")
    if rep["issues"]:
        print("First 10 issues:")
        for it in rep["issues"][:10]:
            print(it)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
