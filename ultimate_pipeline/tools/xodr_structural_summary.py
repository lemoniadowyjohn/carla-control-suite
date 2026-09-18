#!/usr/bin/env python3
"""
Deterministic structural summary for OpenDRIVE (.xodr) files.

Stdlib-only (ElementTree/JSON/hashlib). Avoids CARLA imports and normalizes
line endings before hashing/parsing to keep outputs stable across platforms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict
import xml.etree.ElementTree as ET
from ultimate_pipeline.core.georef_utils import parse_georeference


def _normalize_bytes(data: bytes) -> bytes:
    """Normalize line endings for deterministic hashing/parsing."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _parse_float(text: str | None) -> float | None:
    """Parse a float safely, returning None on failure or non-finite values."""
    if text is None:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _stable_float(value: float | None) -> float | None:
    """Clamp float representation to 6 decimals for stable JSON output."""
    if value is None:
        return None
    return float(f"{value:.6f}")


def _header_bounds(header: ET.Element | None) -> Dict[str, float | None]:
    bounds = {}
    for key in ("north", "south", "east", "west"):
        bounds[key] = _stable_float(_parse_float(header.get(key) if header is not None else None))
    return bounds


def _header_offset(header: ET.Element | None) -> Dict[str, float | None]:
    offset = header.find("offset") if header is not None else None
    values: Dict[str, float | None] = {}
    for key in ("x", "y", "z", "hdg"):
        values[key] = _stable_float(_parse_float(offset.get(key) if offset is not None else None))
    return values


def summarize_xodr(xodr_path: Path) -> Dict[str, Any]:
    """
    Produce a deterministic structural summary for an OpenDRIVE file.
    """
    raw = xodr_path.read_bytes()
    normalized = _normalize_bytes(raw)
    root = ET.fromstring(normalized)

    roads = root.findall("road")
    road_count = len(roads)
    junction_count = sum(1 for road in roads if road.get("junction") not in (None, "-1"))

    total_length = 0.0
    for road in roads:
        length_val = _parse_float(road.get("length"))
        if length_val is not None:
            total_length += length_val
    total_length = _stable_float(total_length)

    lane_section_count = len(root.findall(".//laneSection"))
    lane_count_total = 0
    for lane in root.findall(".//lane"):
        lane_id = lane.get("id")
        if lane_id is not None and lane_id.strip() == "0":
            continue
        lane_count_total += 1

    header = root.find("header")
    geo = header.find("geoReference") if header is not None else root.find(".//geoReference")
    has_geo = geo is not None
    geo_norm = None
    geo_params_complete = None
    if geo is not None and geo.text:
        valid, params_complete, norm = parse_georeference(geo.text)
        geo_norm = norm or None
        geo_params_complete = bool(params_complete)

    summary = {
        "xodr_sha256": hashlib.sha256(normalized).hexdigest(),
        "road_count": road_count,
        "junction_count": junction_count,
        "total_road_length_m": total_length,
        "lane_section_count": lane_section_count,
        "lane_count_total": lane_count_total,
        "has_geoReference": has_geo,
        "geoReference_norm": geo_norm,
        "geoReference_params_complete": geo_params_complete,
        "header_bounds": _header_bounds(header),
        "header_offset": _header_offset(header),
    }
    return summary


def _main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic XODR structural summary.")
    parser.add_argument("--xodr", required=True, help="Path to input .xodr file")
    parser.add_argument("--out", required=True, help="Path to write JSON summary")
    args = parser.parse_args()

    summary = summarize_xodr(Path(args.xodr))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json_bytes = (json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    out_path.write_bytes(json_bytes)


if __name__ == "__main__":
    _main()
