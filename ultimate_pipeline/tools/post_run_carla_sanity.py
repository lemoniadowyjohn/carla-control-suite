# ultimate_pipeline/tools/post_run_carla_sanity.py
"""Post-run drivability sanity checks for CARLA/OpenDRIVE.

Design goals:
- Diagnostic by default (no mutation).
- Optional repairs behind flags (default OFF):
  - UP_REPAIR_ROAD_LINK_ENDPOINTS=1: drop clearly-invalid road predecessor/successor links
    when their endpoint distance exceeds tolerance.

Outputs:
- <run_dir>/carla_drivability_sanity.json
- (optional) <run_dir>/carla_drivability_repair.json
- (optional) repaired XODR copy written next to input.

This module is intentionally self-contained and uses only stdlib.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


@dataclass
class Endpoint:
    x: float
    y: float
    hdg: float


def _safe_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _hypot(a: float, b: float) -> float:
    return float(math.hypot(float(a), float(b)))


def _angle_diff(a: float, b: float) -> float:
    # wrap to [-pi, pi]
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return abs(float(d))


def _road_endpoints(road_el: ET.Element) -> Tuple[Optional[Endpoint], Optional[Endpoint]]:
    """Compute start/end endpoints from the first planView geometry only.
    Conservative: enough to detect gross link mistakes.
    """
    plan = road_el.find("planView")
    if plan is None:
        return None, None
    geoms = plan.findall("geometry")
    if not geoms:
        return None, None

    # Use first geometry for start
    g0 = geoms[0]
    x0 = _safe_float(g0.get("x"))
    y0 = _safe_float(g0.get("y"))
    hdg0 = _safe_float(g0.get("hdg"))

    # Approximate end using last geometry anchor + length along its heading
    gl = geoms[-1]
    xl = _safe_float(gl.get("x"))
    yl = _safe_float(gl.get("y"))
    hdgl = _safe_float(gl.get("hdg"))
    L = _safe_float(gl.get("length"), 0.0)
    xe = xl + L * math.cos(hdgl)
    ye = yl + L * math.sin(hdgl)

    return Endpoint(x0, y0, hdg0), Endpoint(xe, ye, hdgl)


def _parse_links(road_el: ET.Element) -> Dict[str, Optional[Tuple[str, str]]]:
    """Return predecessor/successor as (elementType, elementId)."""
    link = road_el.find("link")
    out: Dict[str, Optional[Tuple[str, str]]] = {"predecessor": None, "successor": None}
    if link is None:
        return out
    for tag in ("predecessor", "successor"):
        el = link.find(tag)
        if el is None:
            continue
        etype = el.get("elementType")
        eid = el.get("elementId")
        if etype and eid:
            out[tag] = (etype, eid)
    return out


def _load_xodr(path: Path) -> ET.ElementTree:
    return ET.parse(path)


def compute_road_link_endpoint_errors(xodr_path: Path) -> Dict:
    tree = _load_xodr(xodr_path)
    root = tree.getroot()

    roads = root.findall("road")
    by_id: Dict[str, ET.Element] = {}
    for r in roads:
        rid = r.get("id")
        if rid is not None:
            by_id[str(rid)] = r

    # Precompute endpoints
    endpoints: Dict[str, Tuple[Optional[Endpoint], Optional[Endpoint]]] = {}
    for rid, r in by_id.items():
        endpoints[rid] = _road_endpoints(r)

    errors: List[Dict] = []
    for rid, r in by_id.items():
        links = _parse_links(r)
        a_start, a_end = endpoints.get(rid, (None, None))
        if a_start is None or a_end is None:
            continue

        for dir_tag, ref in links.items():
            if ref is None:
                continue
            etype, eid = ref
            if etype != "road":
                # ignore junction refs here
                continue
            b = by_id.get(str(eid))
            if b is None:
                errors.append({
                    "road_id": rid,
                    "dir": dir_tag,
                    "ref_road_id": str(eid),
                    "kind": "missing_ref",
                    "abs_error_m": None,
                    "abs_hdg_error_rad": None,
                })
                continue

            b_start, b_end = endpoints.get(str(eid), (None, None))
            if b_start is None or b_end is None:
                continue

            # Conservative: predecessor should connect to our start; successor to our end.
            a_pt = a_start if dir_tag == "predecessor" else a_end

            # Try both ends of referenced road; choose closest.
            cand = [
                (b_start, "start"),
                (b_end, "end"),
            ]
            best = None
            for bp, side in cand:
                d = _hypot(a_pt.x - bp.x, a_pt.y - bp.y)
                h = _angle_diff(a_pt.hdg, bp.hdg)
                score = d + 0.5 * h  # arbitrary combined score
                if best is None or score < best[0]:
                    best = (score, d, h, side)

            if best is None:
                continue

            _, d, h, side = best
            errors.append({
                "road_id": rid,
                "dir": dir_tag,
                "ref_road_id": str(eid),
                "ref_side_used": side,
                "kind": "endpoint_distance",
                "abs_error_m": float(d),
                "abs_hdg_error_rad": float(h),
            })

    max_abs = None
    max_hdg = None
    for e in errors:
        if e.get("abs_error_m") is not None:
            max_abs = e["abs_error_m"] if max_abs is None else max(max_abs, e["abs_error_m"])
        if e.get("abs_hdg_error_rad") is not None:
            max_hdg = e["abs_hdg_error_rad"] if max_hdg is None else max(max_hdg, e["abs_hdg_error_rad"])

    return {
        "xodr_path": str(xodr_path),
        "error_count": len(errors),
        "max_abs_error_m": max_abs,
        "max_abs_hdg_error_rad": max_hdg,
        "errors": errors[:2000],  # cap to keep artifacts small
        "note": "Conservative endpoint error estimator (planView anchors only).",
    }


def optional_repair_drop_bad_links(xodr_path: Path, out_path: Path, tol_m: float) -> Dict:
    """Optional repair: drop road predecessor/successor refs when endpoint distance > tol_m.
    Does NOT invent new links. Safe-ish because it only removes obviously-bad edges.
    """
    tree = _load_xodr(xodr_path)
    root = tree.getroot()
    by_id = {str(r.get("id")): r for r in root.findall("road") if r.get("id") is not None}
    endpoints = {rid: _road_endpoints(r) for rid, r in by_id.items()}

    dropped = 0
    for rid, r in by_id.items():
        links = r.find("link")
        if links is None:
            continue
        for dir_tag in ("predecessor", "successor"):
            el = links.find(dir_tag)
            if el is None:
                continue
            if el.get("elementType") != "road":
                continue
            ref_id = el.get("elementId")
            if ref_id is None or str(ref_id) not in by_id:
                continue

            a_start, a_end = endpoints.get(rid, (None, None))
            b_start, b_end = endpoints.get(str(ref_id), (None, None))
            if a_start is None or a_end is None or b_start is None or b_end is None:
                continue

            a_pt = a_start if dir_tag == "predecessor" else a_end
            d1 = _hypot(a_pt.x - b_start.x, a_pt.y - b_start.y)
            d2 = _hypot(a_pt.x - b_end.x, a_pt.y - b_end.y)
            d = min(d1, d2)
            if d > tol_m:
                links.remove(el)
                dropped += 1

    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    return {"repaired": True, "dropped_link_count": dropped, "tol_m": float(tol_m), "out_xodr": str(out_path)}


def write_drivability_sanity(run_dir: Path, xodr_path: Path) -> None:
    run_dir = Path(run_dir)
    xodr_path = Path(xodr_path)

    report = compute_road_link_endpoint_errors(xodr_path)
    out = run_dir / "carla_drivability_sanity.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    repair_flag = os.getenv("UP_REPAIR_ROAD_LINK_ENDPOINTS", "").strip().lower() in ("1", "true", "yes", "on")
    if not repair_flag:
        return

    tol_m = float(os.getenv("UP_REPAIR_ROAD_LINK_TOL_M", "15"))  # default tolerance, repair is opt-in
    repaired = run_dir / (xodr_path.stem + "__repaired_links.xodr")
    repair_report = optional_repair_drop_bad_links(xodr_path, repaired, tol_m)
    (run_dir / "carla_drivability_repair.json").write_text(
        json.dumps(repair_report, indent=2, sort_keys=True), encoding="utf-8"
    )


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--xodr", required=True)
    args = ap.parse_args()
    write_drivability_sanity(Path(args.run_dir), Path(args.xodr))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
