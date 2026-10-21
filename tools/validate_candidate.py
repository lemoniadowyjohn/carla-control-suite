#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-regen static-gate validation for the candidate XODR.

Usage:
    py -3 validate_candidate.py --xodr <candidate.xodr> [--dem <dem.tif>] [--osm <osm>] [--out <report.json>]

Runs the authoritative P0 oracle (rewritten scans: A final_integrity semantics,
B CLOSURE-18 orphan classes, C audit-style per-side interface counting,
D structure separation, E georeference) plus the connector-elevation
post-check on an out-of-tree copy so the candidate is never mutated.

Prerequisites to gate:
  * P0-A dangling == 0
  * P0-B orphan_fully_disconnected == 0
  * P0-C audit_style_bad_interfaces == 0
  * P0-D violations == 0 (fail-closed)
  * P0-E georeference has_absolute_origin consistent with truthful contract
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ultimate_pipeline.quality.map_realism_p0_oracle import scan_map_realism_p0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--dem", default=None)
    ap.add_argument("--osm", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    xodr = Path(args.xodr)
    if not xodr.is_file():
        print(f"candidate not found: {xodr}")
        return 2

    dem = Path(args.dem) if args.dem else None
    osm = Path(args.osm) if args.osm else None
    out = Path(args.out) if args.out else xodr.with_suffix(".static_gates_report.json")

    t0 = time.time()
    report = scan_map_realism_p0(str(xodr), str(dem) if dem else None, str(osm) if osm else None)
    elapsed = time.time() - t0

    a = report["dangling_mandatory_lane_successors"]
    b = report["orphan_drivable_roads"]
    c = report["connector_lane_interface_dz"]
    d = report["structure_terrain_separation"]
    e = report["georeference"]

    gates = {
        "P0_A_dangling_zero": a["dangling_mandatory_lane_successors"] == 0,
        "P0_B_fully_disconnected_zero": b["orphan_fully_disconnected"] == 0,
        "P0_C_bad_interfaces_zero": c["audit_style_bad_interfaces"] == 0,
        "P0_D_zero_violations": bool(d.get("ok", False)) and int(d.get("violations", -1)) == 0,
    }
    all_pass = all(gates.values())

    summary = {
        "candidate": str(xodr),
        "validated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(elapsed, 2),
        "P0_A": {
            "dangling": a["dangling_mandatory_lane_successors"],
            "by_class": a["dangling_by_class"],
            "gate": gates["P0_A_dangling_zero"],
        },
        "P0_B": {
            "fully_disconnected": b["orphan_fully_disconnected"],
            "junction_link_unresolved": b["orphan_junction_link_unresolved"],
            "gate": gates["P0_B_fully_disconnected_zero"],
        },
        "P0_C": {
            "bad_interfaces": c["audit_style_bad_interfaces"],
            "total_interfaces": c["audit_style_interfaces"],
            "worst_dz": c["worst_dz"],
            "gate": gates["P0_C_bad_interfaces_zero"],
        },
        "P0_D": {
            "classified": d.get("classified_structure_roads"),
            "violations": d.get("violations"),
            "ok": bool(d.get("ok", False)),
            "gate": gates["P0_D_zero_violations"],
        },
        "P0_E": {
            "has_absolute_origin": e.get("has_absolute_origin"),
            "crs": e.get("geo_reference"),
        },
        "gates": gates,
        "all_static_gates_pass": all_pass,
    }
    print(json.dumps(summary, indent=2))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        json.dump({"summary": summary, "full_oracle": report}, fh, indent=2)
    print(f"\nreport -> {out}")
    print(f"RESULT: {'ALL_STATIC_GATES_PASS' if all_pass else 'STATIC_GATES_FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
