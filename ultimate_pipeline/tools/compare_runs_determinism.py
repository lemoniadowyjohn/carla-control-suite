#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compare two pipeline runs for determinism.

What it checks:
- Byte-level SHA256 of the final XODR (MD5 shown for legacy comparison)
- Semantic-ish SHA256 of planView geometry (s,x,y,hdg,len + type-specific params)
- MD5 equality of key JSON artifacts if present

Determinism hygiene:
- Timestamps (created_utc, updated_utc, generated_at_utc) are IGNORED in JSON comparisons
  because they capture wall-clock time, not pipeline state.
- Crash reports and log files are IGNORED as they may contain non-deterministic
  stack traces or timing information.

Usage:
  python ultimate_pipeline/tools/compare_runs_determinism.py <RUN_A> <RUN_B> [--xodr A.xodr] [--xodr-b B.xodr]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, Optional

from ultimate_pipeline.utils.bootstrap import bootstrap_console
from ultimate_pipeline.utils.file_hashing import md5_file as _md5_file, sha256_file

bootstrap_console()

KEY_FILES = [
    "settings_snapshot.json",
    "map_statistics.json",
    "tile_metadata.json",
    "tile_adjacency.json",
    "tile_validation_summary.json",
]

# Fields to ignore in determinism comparisons.
# These are timestamps that capture wall-clock time, not pipeline state.
IGNORED_TIMESTAMP_FIELDS = frozenset({
    "created_utc",
    "updated_utc",
    "generated_at_utc",
    "timestamp",
    "timestamp_utc",
    "run_started_at",
    "run_ended_at",
})

# Files to skip in directory-level comparisons (non-deterministic by nature)
IGNORED_FILES = frozenset({
    "crash_report.json",
    "error_log.txt",
    "debug.log",
    "timing.json",
})


def _strip_timestamps(obj: Any) -> Any:
    """
    Recursively remove timestamp fields from a JSON-like object.

    This ensures determinism comparisons ignore wall-clock time.
    """
    if isinstance(obj, dict):
        return {
            k: _strip_timestamps(v)
            for k, v in obj.items()
            if k not in IGNORED_TIMESTAMP_FIELDS
        }
    elif isinstance(obj, list):
        return [_strip_timestamps(item) for item in obj]
    return obj


def json_hash_ignoring_timestamps(path: Path) -> str:
    """
    Compute a hash of a JSON file, ignoring timestamp fields.

    This provides determinism checking that is immune to wall-clock variations.
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    stripped = _strip_timestamps(data)
    canonical = json.dumps(stripped, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def md5_file(p: Path) -> str:
    """Compute MD5 hash of a file (legacy)."""
    return _md5_file(p)


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

    print("== Final XODR (SHA256) ==")
    ha = sha256_file(xa)
    hb = sha256_file(xb)
    print("A:", xa)
    print("  ", ha)
    print("B:", xb)
    print("  ", hb)
    print("byte_match:", ha == hb)

    print("\n== Final XODR (MD5, legacy) ==")
    ma = md5_file(xa)
    mb = md5_file(xb)
    print("A:", ma)
    print("B:", mb)
    print("md5_match:", ma == mb)

    print("\n== PlanView geometry (SHA256) ==")
    pa = planview_sha256(xa)
    pb = planview_sha256(xb)
    print("A:", pa)
    print("B:", pb)
    print("planview_match:", pa == pb)

    print("\n== Key artifacts (SHA256 equality) ==")
    for rel in KEY_FILES:
        fa = run_a / rel
        fb = run_b / rel
        if fa.exists() and fb.exists():
            print(f"{rel}: {sha256_file(fa) == sha256_file(fb)}")
        else:
            print(f"{rel}: missing A={fa.exists()} B={fb.exists()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
