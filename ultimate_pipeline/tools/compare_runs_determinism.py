#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compare two pipeline runs for determinism.

What it checks:
- Byte-level MD5 of the final XODR
- Semantic-ish SHA256 of planView geometry (s,x,y,hdg,len + type-specific params)
- MD5 equality of key JSON artifacts if present

Usage:
  python ultimate_pipeline/tools/compare_runs_determinism.py <RUN_A> <RUN_B> [--xodr A.xodr] [--xodr-b B.xodr]
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Iterable, Optional

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()

KEY_FILES = [
    "settings_snapshot.json",
    "map_statistics.json",
    "tile_metadata.json",
    "tile_adjacency.json",
    "tile_validation_summary.json",
]


def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _iter_planview_geoms(xodr_path: Path) -> Iterable[str]:
    """Yield a stable textual signature for each <geometry> element."""
    tree = ET.parse(str(xodr_path))
    root = tree.getroot()

    for road in root.findall(".//road"):
        rid = road.get("id", "")
        planview = road.find("planView")
        if planview is None:
            continue

        for geom in planview.findall("geometry"):
            s = geom.get("s", "")
            x = geom.get("x", "")
            y = geom.get("y", "")
            hdg = geom.get("hdg", "")
            length = geom.get("length", "")

            child = None
            for t in ("line", "arc", "spiral", "poly3", "paramPoly3"):
                c = geom.find(t)
                if c is not None:
                    child = c
                    gtype = t
                    break
            else:
                gtype = "unknown"

            params = ""
            if child is not None:
                items = sorted(child.attrib.items(), key=lambda kv: kv[0])
                params = ";".join(f"{k}={v}" for k, v in items)

            yield f"{rid}|{s}|{x}|{y}|{hdg}|{length}|{gtype}|{params}"


def planview_sha256(xodr_path: Path) -> str:
    sig = "\n".join(_iter_planview_geoms(xodr_path))
    return sha256_text(sig)


def _pick_final_xodr(run_dir: Path, override: Optional[str]) -> Path:
    if override:
        p = (run_dir / override) if not Path(override).is_absolute() else Path(override)
        if not p.exists():
            raise FileNotFoundError(p)
        return p

    candidates = sorted(run_dir.glob("08_final*_laneSectionFixed.xodr"))
    if candidates:
        return candidates[0]
    candidates = sorted(run_dir.glob("08_final*.xodr"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No final XODR found in {run_dir}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a", type=Path)
    ap.add_argument("run_b", type=Path)
    ap.add_argument("--xodr", dest="xodr_a", default=None, help="Override XODR path or filename relative to RUN_A")
    ap.add_argument("--xodr-b", dest="xodr_b", default=None, help="Override XODR path or filename relative to RUN_B")
    args = ap.parse_args()

    run_a: Path = args.run_a
    run_b: Path = args.run_b

    xa = _pick_final_xodr(run_a, args.xodr_a)
    xb = _pick_final_xodr(run_b, args.xodr_b)

    print("== Final XODR (MD5) ==")
    ha = md5_file(xa)
    hb = md5_file(xb)
    print("A:", xa)
    print("  ", ha)
    print("B:", xb)
    print("  ", hb)
    print("byte_match:", ha == hb)

    print("\n== PlanView geometry (SHA256) ==")
    pa = planview_sha256(xa)
    pb = planview_sha256(xb)
    print("A:", pa)
    print("B:", pb)
    print("planview_match:", pa == pb)

    print("\n== Key artifacts (MD5 equality) ==")
    for rel in KEY_FILES:
        fa = run_a / rel
        fb = run_b / rel
        if fa.exists() and fb.exists():
            print(f"{rel}: {md5_file(fa) == md5_file(fb)}")
        else:
            print(f"{rel}: missing A={fa.exists()} B={fb.exists()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
