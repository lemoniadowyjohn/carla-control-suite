#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Experiment: OSM→XODR determinism.

Requirement coverage:
 - "When converting OSM to CARLA, evaluate the map and check if the created map changes when converting the same OSM map into a CARLA map."

This script repeatedly converts the *same* OSM file into XODR and compares:
 - file hashes
 - basic structural signatures (roads, junctions, total length)

Output:
 - JSON report with per-run hashes + signatures
 - all produced XODR files in out-dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.osm.osm_to_xodr_wrapper import convert_osm_to_xodr, OSMToXODRConfig


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _signature(xodr_path: Path) -> dict:
    root = ET.parse(xodr_path).getroot()
    roads = root.findall("road")
    juncs = root.findall("junction")
    total_len = 0.0
    for r in roads:
        try:
            total_len += float(r.get("length", "0") or 0.0)
        except Exception:
            pass
    return {
        "num_roads": len(roads),
        "num_junctions": len(juncs),
        "total_road_length": float(total_len),
    }


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", required=True, help="path to ingolstadt.osm (already cut by GPS bounds)")
    ap.add_argument("--out-dir", default="out_osm2xodr_determinism")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tool", default="", help="optional explicit tool/script path")
    ap.add_argument("--carla-root", default="", help="optional CARLA_ROOT override")
    ap.add_argument("--keep", action="store_true", help="keep previously generated files")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = OSMToXODRConfig(
        carla_root=args.carla_root or None,
        tool_path=args.tool or None,
        overwrite=not args.keep,
    )

    runs = []
    for i in range(int(args.runs)):
        out_xodr = out_dir / f"run_{i:03d}.xodr"
        convert_osm_to_xodr(args.osm, out_xodr, cfg)
        runs.append(
            {
                "i": i,
                "xodr": str(out_xodr),
                "sha256": _sha256(out_xodr),
                "md5": _md5(out_xodr),
                "signature": _signature(out_xodr),
            }
        )
        print(f"[{i}] sha256={runs[-1]['sha256']} md5={runs[-1]['md5']} sig={runs[-1]['signature']}")

    stable = all(r.get("sha256") == runs[0].get("sha256") for r in runs)
    report = {"stable": stable, "runs": runs}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    if stable:
        print(f"✅ Deterministic: all {len(runs)} conversions identical")
    else:
        print(f"⚠ Not deterministic: hashes differ across runs")
        # Show unique hashes for quick reading
        print("unique hashes:", sorted(set(r.get("sha256") for r in runs)))


if __name__ == "__main__":
    main()
