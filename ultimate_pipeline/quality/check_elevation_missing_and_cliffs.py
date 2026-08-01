#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elevation sanity gate (offline, deterministic).

Detects two catastrophic patterns:

1) "Missing" elevation: a large fraction of roads have near-zero elevation everywhere.
2) "Cliffs" at road links: large Z discontinuities between the end of a road and
   the start of its successor.

Why the implementation matters:
- In OpenDRIVE, the elevation polynomial is piecewise and parameterized by s.
- Comparing only the first coefficient `a` at s=0 can produce false positives
  (because the connection happens at s=end, and because later elevation segments
  may override the first).

This gate therefore evaluates elevation at *s=0* and *s=road_length* for each road
using the proper piecewise polynomial.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ElevationGateReport:
    ok: bool
    roads_total: int
    roads_zero_a: int
    roads_nonzero_a: int
    zero_ratio: float
    median_nonzero_a: float
    min_a: float
    max_a: float
    link_pairs_checked: int
    max_link_dz: float
    p99_link_dz: float
    examples: List[Dict[str, Any]]
    thresholds: Dict[str, Any]
    xodr_path: str


def _safe_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else float(default)
    except Exception:
        return float(default)


def _parse_elevation_segments(road: ET.Element) -> List[tuple[float, float, float, float, float]]:
    ep = road.find("elevationProfile")
    if ep is None:
        return []
    segs: List[tuple[float, float, float, float, float]] = []
    for el in ep.findall("elevation"):
        s0 = _safe_float(el.get("s"), 0.0)
        a = _safe_float(el.get("a"), 0.0)
        b = _safe_float(el.get("b"), 0.0)
        c = _safe_float(el.get("c"), 0.0)
        d = _safe_float(el.get("d"), 0.0)
        segs.append((s0, a, b, c, d))
    segs.sort(key=lambda t: t[0])
    return segs


def _elevation_at_s(segs: List[tuple[float, float, float, float, float]], s: float) -> float:
    if not segs:
        return 0.0
    chosen = segs[0]
    for cand in segs:
        if s >= cand[0]:
            chosen = cand
        else:
            break
    s0, a, b, c, d = chosen
    ds = max(0.0, float(s) - float(s0))
    return float(a + b * ds + c * ds * ds + d * ds * ds * ds)


def _road_z_start_end(road: ET.Element) -> tuple[float, float]:
    length = _safe_float(road.get("length"), 0.0)
    segs = _parse_elevation_segments(road)
    z0 = _elevation_at_s(segs, 0.0)
    zend = _elevation_at_s(segs, max(0.0, length))
    return z0, zend


def _road_successor_id(road: ET.Element) -> Optional[str]:
    link = road.find("link")
    if link is None:
        return None
    succ = link.find("successor")
    if succ is None:
        return None
    return succ.get("elementId") or succ.get("id")


def check_elevation_missing_and_cliffs(
    xodr_path: str,
    *,
    zero_a_eps: float = 1e-6,
    max_zero_ratio: float = 0.01,
    max_link_dz_m: float = 50.0,
    max_examples: int = 25,
) -> Dict[str, Any]:
    # This function is used as a *gate* inside long-running pipelines.
    # It must never crash the caller on malformed/partial XODR.
    p = Path(xodr_path)
    try:
        tree = ET.parse(str(p))
        root = tree.getroot()
    except Exception as exc:
        # Return a minimal, machine-parseable failure report.
        return {
            "ok": False,
            "roads_total": 0,
            "roads_zero_a": 0,
            "roads_nonzero_a": 0,
            "zero_ratio": 0.0,
            "median_nonzero_a": 0.0,
            "min_a": 0.0,
            "max_a": 0.0,
            "link_pairs_checked": 0,
            "max_link_dz": 0.0,
            "p99_link_dz": 0.0,
            "examples": [],
            "thresholds": {
                "zero_a_eps": zero_a_eps,
                "max_zero_ratio": max_zero_ratio,
                "max_link_dz_m": max_link_dz_m,
            },
            "xodr_path": str(p),
            "error": f"parse_failed: {type(exc).__name__}: {exc}",
        }

    roads = list(root.findall("road"))

    # Per-road elevation endpoints
    road_z0: Dict[str, float] = {}
    road_zend: Dict[str, float] = {}
    z_samples: List[float] = []
    zeros: List[str] = []

    for r in roads:
        rid = r.get("id", "")
        z0, zend = _road_z_start_end(r)
        road_z0[rid] = float(z0)
        road_zend[rid] = float(zend)
        z_samples.extend([float(z0), float(zend)])

        # "missing" elevation heuristic: both endpoints ~ 0
        if max(abs(z0), abs(zend)) <= float(zero_a_eps):
            zeros.append(rid)

    nonzero = sorted([v for v in z_samples if abs(v) > float(zero_a_eps)])
    median_nonzero = float(nonzero[len(nonzero) // 2]) if nonzero else 0.0
    min_a = float(min(z_samples)) if z_samples else 0.0
    max_a = float(max(z_samples)) if z_samples else 0.0

    dzs: List[float] = []
    examples: List[Dict[str, Any]] = []
    checked = 0
    for r in roads:
        rid = r.get("id", "")
        sid = _road_successor_id(r)
        if not sid:
            continue
        if sid not in road_z0:
            continue
        checked += 1
        # Compare end-of-road Z to start-of-successor Z (connection semantics)
        dz = abs(float(road_zend.get(rid, 0.0)) - float(road_z0.get(sid, 0.0)))
        dzs.append(float(dz))
        if dz > max_link_dz_m and len(examples) < max_examples:
            examples.append(
                {
                    "from": rid,
                    "to": sid,
                    "dz_m": dz,
                    "z_end_from": float(road_zend.get(rid, 0.0)),
                    "z_start_to": float(road_z0.get(sid, 0.0)),
                }
            )

    dzs_sorted = sorted(dzs)
    p99 = float(dzs_sorted[int(0.99 * (len(dzs_sorted) - 1))]) if dzs_sorted else 0.0
    max_dz = float(dzs_sorted[-1]) if dzs_sorted else 0.0

    zero_ratio = (len(zeros) / len(roads)) if roads else 0.0

    ok = True
    if zero_ratio > max_zero_ratio:
        ok = False
    if max_dz > max_link_dz_m:
        ok = False

    rep = ElevationGateReport(
        ok=ok,
        roads_total=len(roads),
        roads_zero_a=len(zeros),
        roads_nonzero_a=max(0, len(roads) - len(zeros)),
        zero_ratio=float(zero_ratio),
        median_nonzero_a=float(median_nonzero),
        min_a=min_a,
        max_a=max_a,
        link_pairs_checked=checked,
        max_link_dz=max_dz,
        p99_link_dz=p99,
        examples=examples,
        thresholds={
            "zero_a_eps": zero_a_eps,
            "max_zero_ratio": max_zero_ratio,
            "max_link_dz_m": max_link_dz_m,
        },
        xodr_path=str(p),
    )
    return asdict(rep)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--max_zero_ratio", type=float, default=float(os.getenv("UP_ELEV_MAX_ZERO_RATIO", "0.01")))
    ap.add_argument("--max_link_dz_m", type=float, default=float(os.getenv("UP_ELEV_MAX_LINK_DZ_M", "50.0")))
    args = ap.parse_args()

    rep = check_elevation_missing_and_cliffs(
        args.xodr,
        max_zero_ratio=args.max_zero_ratio,
        max_link_dz_m=args.max_link_dz_m,
    )

    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    print(json.dumps({"ok": rep["ok"], "zero_ratio": rep["zero_ratio"], "max_link_dz": rep["max_link_dz"]}, indent=2))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
