from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _sample_line(x0: float, y0: float, hdg: float, length: float, step: float) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    n = max(1, int(length / step))
    for i in range(n + 1):
        s = min(length, i * step)
        pts.append((x0 + s * math.cos(hdg), y0 + s * math.sin(hdg)))
    return pts


def _sample_arc(x0: float, y0: float, hdg: float, length: float, curvature: float, step: float) -> List[Tuple[float, float]]:
    if abs(curvature) < 1e-9:
        return _sample_line(x0, y0, hdg, length, step)
    pts: List[Tuple[float, float]] = []
    n = max(1, int(length / step))
    k = curvature
    for i in range(n + 1):
        s = min(length, i * step)
        theta = k * s
        x = x0 + (math.sin(hdg + theta) - math.sin(hdg)) / k
        y = y0 + (-math.cos(hdg + theta) + math.cos(hdg)) / k
        pts.append((x, y))
    return pts


def check_dem_full_coverage(
    xodr_path: str,
    dem_tif_path: str,
    out_json: str,
    step_m: float = 2.0,
    max_samples: int = 250_000,
    xodr_crs_proj4: Optional[str] = None,
    threshold: float = 0.6,
    sampler: Optional[Callable[[float, float], Any]] = None,
) -> Dict[str, Any]:
    """Sample planView geometry points and test whether DEM provides valid elevation.

    Notes:
    - Imports rasterio/pyproj lazily to avoid hard dependency unless invoked.
    - If sampler is provided, it is authoritative and uses the same effective
      header-offset/CRS logic as DEM application.
    - If sampler is not provided and xodr_crs_proj4 is None, assumes XODR XY are
      already in DEM CRS.
    """
    import xml.etree.ElementTree as ET
    import rasterio
    from pyproj import CRS, Transformer

    xodr_path = str(xodr_path)
    dem_tif_path = str(dem_tif_path)

    with rasterio.open(dem_tif_path) as ds:
        dem_crs = ds.crs
        nodata = ds.nodata

        tf = None
        if sampler is None and xodr_crs_proj4:
            xodr_crs = CRS.from_user_input(xodr_crs_proj4)
            tf = Transformer.from_crs(xodr_crs, dem_crs, always_xy=True)

        total = 0
        covered = 0
        uncovered_examples: List[Dict[str, float]] = []

        in_planview = False
        for ev, el in ET.iterparse(xodr_path, events=("start", "end")):
            name = _localname(el.tag)
            if ev == "start":
                if name == "planView":
                    in_planview = True
                continue

            if name == "planView":
                in_planview = False
                el.clear()
                continue

            if in_planview and name == "geometry":
                ax = el.attrib.get("x"); ay = el.attrib.get("y")
                ah = el.attrib.get("hdg"); al = el.attrib.get("length")
                if ax and ay and ah and al:
                    x0 = float(ax); y0 = float(ay); hdg = float(ah); length = float(al)

                    prim = None
                    curvature = 0.0
                    for child in list(el):
                        cname = _localname(child.tag)
                        if cname == "line":
                            prim = "line"
                            break
                        if cname == "arc":
                            prim = "arc"
                            curvature = float(child.attrib.get("curvature", "0.0"))
                            break

                    if prim == "line":
                        pts = _sample_line(x0, y0, hdg, length, step_m)
                    elif prim == "arc":
                        pts = _sample_arc(x0, y0, hdg, length, curvature, step_m)
                    else:
                        pts = []

                    for (x, y) in pts:
                        if total >= max_samples:
                            break
                        if sampler is not None:
                            result = sampler(x, y)
                            if isinstance(result, tuple) and len(result) == 2:
                                val, ok = result
                            else:
                                val = result
                                ok = val is not None
                            X, Y = x, y
                        elif tf:
                            X, Y = tf.transform(x, y)
                            val = next(ds.sample([(X, Y)]))[0]
                            ok = True
                            if nodata is not None and val == nodata:
                                ok = False
                            if not (val == val):  # NaN
                                ok = False
                        else:
                            X, Y = x, y
                            val = next(ds.sample([(X, Y)]))[0]
                            ok = True
                            if nodata is not None and val == nodata:
                                ok = False
                            if not (val == val):  # NaN
                                ok = False

                        total += 1
                        if ok:
                            covered += 1
                        elif len(uncovered_examples) < 200:
                            uncovered_examples.append({"x": x, "y": y, "dem_x": float(X), "dem_y": float(Y)})

                    if total >= max_samples:
                        break

            el.clear()

    report = {
        "xodr_path": xodr_path,
        "dem_tif_path": dem_tif_path,
        "step_m": step_m,
        "max_samples": max_samples,
        "total_samples": total,
        "covered_samples": covered,
        "coverage_ratio": (covered / total) if total else 0.0,
        "threshold": float(threshold),
        "ok": ((covered / total) if total else 0.0) >= float(threshold) if total else False,
        "uncovered_examples": uncovered_examples,
        "sampling_mode": "sampler" if sampler is not None else "direct_transform",
        "projected_bbox_wgs84": getattr(sampler, "_projected_bbox_wgs84", None)
        if sampler is not None
        else None,
        "dem_bounds_wgs84": getattr(sampler, "_dem_bounds_wgs84", None)
        if sampler is not None
        else None,
        "bbox_intersects_dem_bounds_wgs84": getattr(
            sampler, "_bbox_intersects_dem_bounds_wgs84", None
        )
        if sampler is not None
        else None,
        "map_crs_source": getattr(sampler, "_map_crs_source", None)
        if sampler is not None
        else None,
        "header_offset_policy": getattr(sampler, "_header_offset_policy", None)
        if sampler is not None
        else None,
    }
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True)
    ap.add_argument("--dem", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--step", type=float, default=2.0)
    ap.add_argument("--max-samples", type=int, default=250_000)
    ap.add_argument("--xodr-proj4", default=None)
    ap.add_argument("--threshold", type=float, default=0.6)
    args = ap.parse_args()

    check_dem_full_coverage(
        xodr_path=args.xodr,
        dem_tif_path=args.dem,
        out_json=args.out,
        step_m=args.step,
        max_samples=args.max_samples,
        xodr_crs_proj4=args.xodr_proj4,
        threshold=args.threshold,
    )
