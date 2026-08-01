#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate runtime enrichments JSON for CARLA proxy spawning.

The output schema is intentionally compatible with:
  ultimate_pipeline.carla_tools.spawn_enrichments.load_enrichments()
and therefore with run_perception_safe._spawn_runtime_enrichments().
"""

from __future__ import annotations

import argparse
import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.utils.paths import city_dir


REQUIRED_TYPES: Tuple[str, ...] = ("building", "pole", "barrier")

# Corrected semantic blueprint hints for downstream runtime proxy spawning.
BLUEPRINT_HINTS: Dict[str, str] = {
    "building": "static.prop.box01",
    "pole": "static.prop.streetsign",
    "barrier": "static.prop.streetbarrier",
}


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _resolve_output_path(out_arg: str) -> Path:
    p = Path(str(out_arg or "").strip() or "enrichments_runtime.json").expanduser()
    if p.suffix.lower() == ".json":
        return p
    return p / str(SETTINGS.ENRICHMENTS_RUNTIME_DIRNAME) / str(
        SETTINGS.ENRICHMENTS_RUNTIME_JSON_NAME
    )


def _resolve_buildings_path(bbox: str, explicit: Optional[str]) -> Optional[Path]:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    try:
        settings_path = Path(str(SETTINGS.OSM_BUILDINGS_GEOJSON)).expanduser()
        candidates.append(settings_path)
    except Exception:
        pass
    candidates.append(city_dir(bbox) / "osm" / "buildings.geojson")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _resolve_xodr_path(bbox: str, explicit: Optional[str]) -> Optional[Path]:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    try:
        input_xodr = Path(str(SETTINGS.INPUT_XODR)).expanduser()
        candidates.append(input_xodr)
    except Exception:
        pass
    candidates.append(city_dir(bbox) / f"{bbox}_osm_auto.xodr")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _xodr_xy_bounds(xodr_path: Optional[Path]) -> Optional[Dict[str, float]]:
    if xodr_path is None or (not xodr_path.is_file()):
        return None
    try:
        root = ET.parse(xodr_path).getroot()
        header = root.find("header")
        if header is None:
            return None
        west = _coerce_float(header.get("west"))
        east = _coerce_float(header.get("east"))
        south = _coerce_float(header.get("south"))
        north = _coerce_float(header.get("north"))
        if None in (west, east, south, north):
            return None
        if float(east) <= float(west) or float(north) <= float(south):
            return None
        return {
            "west": float(west),
            "east": float(east),
            "south": float(south),
            "north": float(north),
        }
    except Exception:
        return None


def _gps_bounds() -> Dict[str, float]:
    raw = dict(getattr(SETTINGS, "GPS_BOUNDS", None) or SETTINGS.load_gps_bounds())
    return {
        "lat_min": float(raw["lat_min"]),
        "lon_min": float(raw["lon_min"]),
        "lat_max": float(raw["lat_max"]),
        "lon_max": float(raw["lon_max"]),
    }


def _latlon_to_xy(
    *,
    lat: float,
    lon: float,
    gps: Dict[str, float],
    xy: Optional[Dict[str, float]],
) -> Tuple[float, float]:
    # Preferred deterministic mapping: affine projection into observed XODR bounds.
    if xy is not None:
        lon_span = gps["lon_max"] - gps["lon_min"]
        lat_span = gps["lat_max"] - gps["lat_min"]
        if lon_span > 0.0 and lat_span > 0.0:
            x = xy["west"] + ((lon - gps["lon_min"]) / lon_span) * (xy["east"] - xy["west"])
            y = xy["south"] + ((lat - gps["lat_min"]) / lat_span) * (
                xy["north"] - xy["south"]
            )
            return float(x), float(y)

    # Fallback deterministic approximation near bbox origin.
    lat0 = float(gps["lat_min"])
    lon0 = float(gps["lon_min"])
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians((lat0 + gps["lat_max"]) * 0.5))
    x = (lon - lon0) * meters_per_deg_lon
    y = (lat - lat0) * meters_per_deg_lat
    return float(x), float(y)


def _extract_building_centroids(buildings_path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(buildings_path.read_text(encoding="utf-8"))
    out: List[Dict[str, Any]] = []

    # Overpass JSON format with "elements"
    elements = payload.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
            if tags and str(tags.get("building", "")).strip().lower() in {"", "no"}:
                continue
            geom = element.get("geometry")
            if not isinstance(geom, list) or len(geom) < 3:
                continue
            points: List[Tuple[float, float]] = []
            for node in geom:
                if not isinstance(node, dict):
                    continue
                lat = _coerce_float(node.get("lat"))
                lon = _coerce_float(node.get("lon"))
                if lat is None or lon is None:
                    continue
                points.append((lat, lon))
            if len(points) < 3:
                continue
            lat_c = sum(p[0] for p in points) / float(len(points))
            lon_c = sum(p[1] for p in points) / float(len(points))
            height = _coerce_float(tags.get("height"))
            if height is None:
                levels = _coerce_float(tags.get("building:levels"))
                if levels is not None and levels > 0.0:
                    height = max(3.0, levels * 3.0)
            out.append(
                {
                    "lat": float(lat_c),
                    "lon": float(lon_c),
                    "height": float(height if height is not None else 10.0),
                }
            )

    # Standard GeoJSON fallback
    if not out and payload.get("type") == "FeatureCollection":
        features = payload.get("features")
        if isinstance(features, list):
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                geom = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
                if str(geom.get("type", "")) != "Polygon":
                    continue
                coords = geom.get("coordinates")
                if not (isinstance(coords, list) and coords):
                    continue
                ring = coords[0]
                if not isinstance(ring, list) or len(ring) < 3:
                    continue
                lon_lat_points: List[Tuple[float, float]] = []
                for node in ring:
                    if not (isinstance(node, list) and len(node) >= 2):
                        continue
                    lon = _coerce_float(node[0])
                    lat = _coerce_float(node[1])
                    if lat is None or lon is None:
                        continue
                    lon_lat_points.append((lon, lat))
                if len(lon_lat_points) < 3:
                    continue
                lon_c = sum(p[0] for p in lon_lat_points) / float(len(lon_lat_points))
                lat_c = sum(p[1] for p in lon_lat_points) / float(len(lon_lat_points))
                props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
                height = _coerce_float(props.get("height"))
                out.append(
                    {
                        "lat": float(lat_c),
                        "lon": float(lon_c),
                        "height": float(height if height is not None else 10.0),
                    }
                )

    return out


def _synthesize_candidates(
    *,
    gps: Dict[str, float],
    xy: Optional[Dict[str, float]],
    n: int,
) -> List[Dict[str, Any]]:
    # Deterministic lattice across bbox for robust fallback.
    n = max(1, int(n))
    width = int(math.ceil(math.sqrt(float(n))))
    out: List[Dict[str, Any]] = []
    for idx in range(n):
        r = idx // width
        c = idx % width
        lat = gps["lat_min"] + ((r + 1) / float(width + 1)) * (gps["lat_max"] - gps["lat_min"])
        lon = gps["lon_min"] + ((c + 1) / float(width + 1)) * (gps["lon_max"] - gps["lon_min"])
        x, y = _latlon_to_xy(lat=lat, lon=lon, gps=gps, xy=xy)
        out.append({"x": x, "y": y, "height": 10.0})
    return out


def _ensure_minimum_objects(
    *,
    building_points: List[Dict[str, Any]],
    min_objects: int,
) -> List[Dict[str, Any]]:
    min_objects = max(10, int(min_objects))
    if not building_points:
        return []

    out: List[Dict[str, Any]] = []
    n_buildings = max(4, min_objects // 2)
    n_poles = max(3, (min_objects - n_buildings) // 2)
    n_barriers = max(3, min_objects - n_buildings - n_poles)

    for idx in range(n_buildings):
        src = building_points[idx % len(building_points)]
        out.append(
            {
                "id": f"runtime_building_{idx+1:04d}",
                "type": "building",
                "normalized_type": "building",
                "x": float(src["x"]),
                "y": float(src["y"]),
                "z": 0.0,
                "yaw": 0.0,
                "height": float(src.get("height", 10.0)),
                "proxy_blueprint": BLUEPRINT_HINTS["building"],
            }
        )

    for idx in range(n_poles):
        src = building_points[idx % len(building_points)]
        x = float(src["x"]) + 2.0 + float(idx % 3)
        y = float(src["y"]) + (1.5 if (idx % 2 == 0) else -1.5)
        out.append(
            {
                "id": f"runtime_pole_{idx+1:04d}",
                "type": "pole",
                "normalized_type": "pole",
                "x": x,
                "y": y,
                "z": 0.0,
                "yaw": 0.0,
                "proxy_blueprint": BLUEPRINT_HINTS["pole"],
            }
        )

    for idx in range(n_barriers):
        src = building_points[idx % len(building_points)]
        x = float(src["x"]) - 3.5 - float(idx % 2)
        y = float(src["y"]) + (2.5 if (idx % 2 == 0) else -2.5)
        out.append(
            {
                "id": f"runtime_barrier_{idx+1:04d}",
                "type": "barrier",
                "normalized_type": "barrier",
                "x": x,
                "y": y,
                "z": 0.0,
                "yaw": 0.0,
                "proxy_blueprint": BLUEPRINT_HINTS["barrier"],
            }
        )

    return out


def _type_counts(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        t = str(item.get("normalized_type") or item.get("type") or "").strip().lower()
        if not t:
            continue
        counts[t] = counts.get(t, 0) + 1
    return counts


def generate_runtime_enrichments(
    *,
    bbox: str,
    out_path: Path,
    buildings_path: Optional[Path],
    xodr_path: Optional[Path],
    min_objects: int,
) -> Dict[str, Any]:
    gps = _gps_bounds()
    xy = _xodr_xy_bounds(xodr_path)
    raw_candidates: List[Dict[str, Any]] = []
    if buildings_path is not None and buildings_path.is_file():
        raw_candidates = _extract_building_centroids(buildings_path)

    building_points: List[Dict[str, Any]] = []
    for item in raw_candidates:
        lat = _coerce_float(item.get("lat"))
        lon = _coerce_float(item.get("lon"))
        if lat is None or lon is None:
            continue
        x, y = _latlon_to_xy(lat=float(lat), lon=float(lon), gps=gps, xy=xy)
        building_points.append(
            {
                "x": x,
                "y": y,
                "height": float(item.get("height", 10.0)),
            }
        )

    if not building_points:
        building_points = _synthesize_candidates(gps=gps, xy=xy, n=max(10, int(min_objects)))

    objects = _ensure_minimum_objects(
        building_points=building_points,
        min_objects=max(10, int(min_objects)),
    )

    counts = _type_counts(objects)
    missing = [t for t in REQUIRED_TYPES if counts.get(t, 0) <= 0]
    if missing:
        raise RuntimeError(
            f"generated enrichments missing required runtime types: {', '.join(missing)}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "ultimate_pipeline.enrichments_runtime.v1",
        "bbox": str(bbox),
        "required_types": list(REQUIRED_TYPES),
        "source": {
            "buildings_path": str(buildings_path) if buildings_path else None,
            "xodr_path": str(xodr_path) if xodr_path else None,
        },
        "summary": {
            "requested_min_objects": int(min_objects),
            "generated_count": len(objects),
            "type_counts": counts,
        },
        "objects": objects,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return payload


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Generate enrichments_runtime.json from local pipeline inputs."
    )
    ap.add_argument(
        "--bbox",
        default="ingolstadt",
        help="Named bbox/city key used to resolve default input files (default: ingolstadt).",
    )
    ap.add_argument(
        "--out",
        required=True,
        help=(
            "Output path. If it ends with .json, write directly. "
            "Otherwise write <out>/<enrichments_dir>/<enrichments_runtime.json>."
        ),
    )
    ap.add_argument(
        "--buildings",
        default="",
        help="Optional explicit buildings source JSON (Overpass JSON or GeoJSON).",
    )
    ap.add_argument(
        "--xodr",
        default="",
        help="Optional explicit XODR input used to infer map XY bounds.",
    )
    ap.add_argument(
        "--min-objects",
        type=int,
        default=int(getattr(SETTINGS, "ENRICHMENTS_GENERATOR_MIN_OBJECTS", 12)),
        help="Minimum number of generated runtime objects (>=10 enforced).",
    )
    return ap


def main() -> int:
    ap = _build_arg_parser()
    args = ap.parse_args()

    out_path = _resolve_output_path(str(args.out))
    bbox = str(args.bbox or "").strip().lower() or "ingolstadt"
    buildings_path = _resolve_buildings_path(bbox, str(args.buildings or "").strip() or None)
    xodr_path = _resolve_xodr_path(bbox, str(args.xodr or "").strip() or None)

    payload = generate_runtime_enrichments(
        bbox=bbox,
        out_path=out_path,
        buildings_path=buildings_path,
        xodr_path=xodr_path,
        min_objects=max(10, int(args.min_objects)),
    )

    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path),
                "generated_count": int(payload.get("summary", {}).get("generated_count", 0)),
                "type_counts": payload.get("summary", {}).get("type_counts", {}),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

