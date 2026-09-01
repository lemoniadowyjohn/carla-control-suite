#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json, math, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Tuple
from ultimate_pipeline.core.georef_utils import parse_georeference

def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag

def _extract_planview_points_stream(xodr_path: Path) -> List[Tuple[float,float]]:
    pts=[]; stack=[]
    for ev, el in ET.iterparse(str(xodr_path), events=("start","end")):
        name=_localname(el.tag)
        if ev=="start":
            stack.append(name)
            if name=="geometry" and len(stack)>=2 and stack[-2]=="planView":
                x=el.attrib.get("x"); y=el.attrib.get("y")
                if x is None or y is None:
                    continue
                try:
                    fx, fy = float(x), float(y)
                except Exception:
                    continue
                # float() accepts "nan"/"inf" strings; a non-finite point
                # here would silently corrupt min()/max() in _bbox (NaN
                # comparisons are always False, so the result depends on
                # iteration order rather than being a real bound).
                if math.isfinite(fx) and math.isfinite(fy):
                    pts.append((fx, fy))
        else:
            if stack: stack.pop()
            el.clear()
    return pts

def _bbox(pts: List[Tuple[float,float]]) -> Dict[str,float]:
    if not pts: return {"minx":0.0,"maxx":0.0,"miny":0.0,"maxy":0.0}
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return {"minx":min(xs),"maxx":max(xs),"miny":min(ys),"maxy":max(ys)}

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--xodr", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args=ap.parse_args()

    tree=ET.parse(str(args.xodr))
    root=tree.getroot()
    header=root.find("header")
    geo_ref=None; offset=None
    geo_norm=None
    geo_params_complete=None
    geo_valid=None
    if header is not None:
        gr=header.find("geoReference")
        geo_ref=(gr.text.strip() if gr is not None and gr.text else None)
        geo_valid, params_complete, norm = parse_georeference(geo_ref)
        geo_norm = norm or None
        geo_params_complete = bool(params_complete)
        off=header.find("offset")
        if off is not None:
            offset={k: off.get(k) for k in ("x","y","z","hdg") if off.get(k) is not None}

    pts=_extract_planview_points_stream(args.xodr)
    bb=_bbox(pts)
    max_abs=max(abs(bb["minx"]), abs(bb["maxx"]), abs(bb["miny"]), abs(bb["maxy"])) if pts else 0.0

    report: Dict[str,Any] = {
        "xodr": str(args.xodr.resolve()),
        "geoReference": geo_ref,
        "geoReference_norm": geo_norm,
        "geoReference_valid": geo_valid,
        "geoReference_params_complete": geo_params_complete,
        "offset": offset,
        "planView_geometry_points": len(pts),
        "bbox": bb,
        "max_abs_coord": max_abs,
        "coord_scale_hint": "large_global" if max_abs > 50000 else "local_meters",
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
