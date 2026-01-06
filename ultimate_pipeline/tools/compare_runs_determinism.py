#!/usr/bin/env python3
"""
Compare two pipeline runs for determinism:
- MD5 of final XODR (byte-level)
- SHA256 of planView geometry (semantic-ish)
- MD5 of key JSON artifacts
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

KEY_FILES = [
    "settings_snapshot.json",
    "map_statistics.json",
    "tile_metadata.json",
    "tile_adjacency.json",
    "gate_failures.json",
]

def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def pick_final_xodr(run_dir: Path) -> Path:
    cand = sorted(run_dir.glob("08_final_*.xodr"))
    if cand:
        return cand[0]
    xodrs = sorted(run_dir.glob("*.xodr"))
    if not xodrs:
        raise FileNotFoundError(f"No .xodr in {run_dir}")
    return xodrs[-1]

def semantic_hash_planview(xodr_path: Path, ndigits: int = 6) -> str:
    def r(x: str) -> str:
        try:
            return f"{float(x):.{ndigits}f}"
        except Exception:
            return x

    root = ET.parse(xodr_path).getroot()
    rows = []
    for road in sorted(root.findall("road"), key=lambda rr: int(rr.get("id", "0"))):
        rid = road.get("id", "")
        pv = road.find("planView")
        if pv is None:
            continue
        for g in sorted(pv.findall("geometry"), key=lambda gg: float(gg.get("s", "0"))):
            base = (rid, r(g.get("s","0")), r(g.get("x","0")), r(g.get("y","0")), r(g.get("hdg","0")), r(g.get("length","0")))
            child = next(iter(g), None)
            if child is None:
                rows.append("|".join(base) + "|NONE")
            else:
                attrs = ",".join(f"{k}={r(child.attrib[k])}" for k in sorted(child.attrib.keys()))
                rows.append("|".join(base) + f"|{child.tag}|{attrs}")

    h = hashlib.sha256()
    for line in rows:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--out-root", type=str, default="ultimate_pipeline_out")
    ap.add_argument("--run-a", type=str)
    ap.add_argument("--run-b", type=str)
    args = ap.parse_args()

    if args.auto:
        out_root = Path(args.out_root)
        runs = sorted([p for p in out_root.iterdir() if p.is_dir() and p.name[:8].isdigit()], key=lambda p: p.name)
        if len(runs) < 2:
            raise SystemExit("Need at least 2 runs in ultimate_pipeline_out")
        run_a, run_b = runs[-2], runs[-1]
    else:
        if not args.run_a or not args.run_b:
            raise SystemExit("Use --auto or provide --run-a and --run-b")
        run_a, run_b = Path(args.run_a), Path(args.run_b)

    fa, fb = pick_final_xodr(run_a), pick_final_xodr(run_b)

    print("== Final XODR (byte MD5) ==")
    print("A:", md5_file(fa))
    print("B:", md5_file(fb))

    print("\n== Final XODR (planView semantic SHA256) ==")
    ha, hb = semantic_hash_planview(fa), semantic_hash_planview(fb)
    print("A:", ha)
    print("B:", hb)
    print("planview_match:", ha == hb)

    print("\n== Key artifacts (MD5) ==")
    for rel in KEY_FILES:
        pa, pb = run_a / rel, run_b / rel
        if pa.exists() and pb.exists():
            print(f"{rel}: {md5_file(pa) == md5_file(pb)}")
        else:
            print(f"{rel}: missing A={pa.exists()} B={pb.exists()}")

if __name__ == "__main__":
    main()
