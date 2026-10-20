"""Bounded, read-only local OpenDRIVE/OSM/DEM inspection.

Selecting a map file is NOT a CARLA runtime map load or proof of cooked content.
"""
from __future__ import annotations

import math
from pathlib import Path

SUPPORTED = frozenset({".xodr", ".osm", ".tif", ".tiff"})
MAX_XML_BYTES = 256 * 1024 * 1024


class MapInspectionError(ValueError):
    pass


def sample_geometry(x: float, y: float, heading: float, length: float,
                    curvature: float = 0.0) -> list[tuple[float, float]]:
    """Sample an OpenDRIVE line/arc by its plan-view origin and local arc length."""
    if length < 0 or not all(math.isfinite(v) for v in (x, y, heading, length, curvature)):
        raise MapInspectionError("geometry contains negative length or non-finite coordinates")
    count = max(2, min(16, int(length // 8) + 2))
    output = []
    for i in range(count):
        s = length * i / (count - 1)
        if abs(curvature) < 1e-10:
            px = x + s * math.cos(heading)
            py = y + s * math.sin(heading)
        else:
            px = x + (math.sin(heading + curvature * s) - math.sin(heading)) / curvature
            py = y - (math.cos(heading + curvature * s) - math.cos(heading)) / curvature
        output.append((px, py))
    return output


def evaluate_elevation(records: list[list[float]], s: float) -> float:
    """OpenDRIVE z(s) polynomial for the active road elevation section."""
    if not records or not math.isfinite(s):
        raise ValueError("profile and finite s required")
    eligible = [r for r in records if r[0] <= s]
    active = max(eligible or records[:1], key=lambda row: row[0])
    offset, a, b, c, d = active
    ds = max(0.0, s - offset)
    return a + b * ds + c * ds**2 + d * ds**3


def inspect_xml_map(path: str | Path, max_segments: int = 2400) -> dict:
    """Stream a selected map with entity-safe XML parsing and bounded plot samples."""
    from defusedxml.ElementTree import iterparse

    p = Path(path)
    if p.suffix.lower() not in {".osm", ".xodr"}:
        raise MapInspectionError("choose an .osm or .xodr file")
    size = p.stat().st_size
    if not 0 < size <= MAX_XML_BYTES:
        raise MapInspectionError(f"XML file must be 1..{MAX_XML_BYTES} bytes")
    segments: list[list[tuple[float, float]]] = []
    roads = junctions = ways = nodes = elevation_records = 0
    elevation_origins: list[float] = []
    elevation_profiles: list[dict] = []
    georeference = "UNKNOWN"
    with p.open("rb") as handle:
        for event, el in iterparse(handle, events=("end",), forbid_dtd=True,
                                     forbid_entities=True, forbid_external=True):
            if el.tag == "road" and p.suffix.lower() == ".xodr":
                roads += 1
                if len(segments) < max_segments:
                    for geom in el.findall("./planView/geometry"):
                        if len(segments) >= max_segments:
                            break
                        try:
                            arc = geom.find("arc")
                            if geom.find("line") is None and arc is None:
                                continue
                            segments.append(sample_geometry(
                                float(geom.attrib["x"]), float(geom.attrib["y"]),
                                float(geom.attrib["hdg"]), float(geom.attrib["length"]),
                                float(arc.attrib["curvature"]) if arc is not None else 0.0,
                            ))
                        except (ValueError, KeyError, OverflowError):
                            continue
                selected_profile = []
                for elevation in el.findall("./elevationProfile/elevation"):
                    elevation_records += 1
                    try:
                        if len(elevation_origins) < 250000:
                            elevation_origins.append(float(elevation.attrib["a"]))
                        if len(selected_profile) < 512:
                            selected_profile.append([float(elevation.attrib[k])
                                for k in ("s", "a", "b", "c", "d")])
                    except (KeyError, ValueError):
                        pass
                if selected_profile and len(elevation_profiles) < 30:
                    elevation_profiles.append({"road_id": el.attrib.get("id", "UNKNOWN"),
                                               "length": float(el.attrib.get("length", "0")),
                                               "coefficients": selected_profile})
                el.clear()
            elif el.tag == "junction":
                junctions += 1
                el.clear()
            elif el.tag == "header":
                geo = el.find("geoReference")
                if geo is not None and geo.text:
                    georeference = geo.text.strip()[:350]
                el.clear()
            elif p.suffix.lower() == ".osm" and el.tag in ("node", "way"):
                nodes += int(el.tag == "node")
                ways += int(el.tag == "way")
                el.clear()
    return {"file": p.name, "size_bytes": size, "kind": p.suffix.lower(),
            "roads": roads, "junctions": junctions, "osm_nodes": nodes, "osm_ways": ways,
            "elevation_records": elevation_records,
            "elevation_a_min": min(elevation_origins) if elevation_origins else None,
            "elevation_a_max": max(elevation_origins) if elevation_origins else None,
            "georeference": georeference, "segments": segments,
            "elevation_profiles": elevation_profiles,
            "plot_note": "Sampled line/arc geometry only; not a validated map or cooked CARLA asset"}


def inspect_dem(path: str | Path) -> dict:
    """Read raster elevation summary via optional rasterio (not a map cook)."""
    p = Path(path)
    if p.suffix.lower() not in {".tif", ".tiff"}:
        raise MapInspectionError("select a GeoTIFF DEM")
    try:
        import rasterio
        import numpy as np
    except ImportError as exc:
        raise MapInspectionError("DEM preview requires rasterio and numpy") from exc
    with rasterio.open(p) as ds:
        if ds.count < 1:
            raise MapInspectionError("raster has no bands")
        scale_h = min(ds.height, 320)
        scale_w = min(ds.width, 320)
        values = ds.read(1, out_shape=(scale_h, scale_w), masked=True)
        valid = values.compressed()
        if not valid.size:
            raise MapInspectionError("DEM contains no valid sampled pixels")
        valid = valid[np.isfinite(valid)]
        if not valid.size:
            raise MapInspectionError("DEM has no finite sample values")
        scaled = values.astype("float64").filled(float("nan"))
        low, high = float(valid.min()), float(valid.max())
        gray = np.nan_to_num((scaled - low) / max(high - low, 1e-9), nan=0.0)
        preview = (np.clip(gray, 0, 1) * 255).astype("uint8")
        return {"raster_preview": {"width": scale_w, "height": scale_h,
                                   "pixels": preview.tobytes()},
                "file": p.name, "kind": "dem", "width": ds.width,
                "height": ds.height, "crs": str(ds.crs or "UNKNOWN"),
                "bounds": tuple(ds.bounds), "sampled_min": float(valid.min()),
                "sampled_max": float(valid.max()), "sampled_mean": float(valid.mean()),
                "sampled_cells": int(valid.size),
                "note": "Downsampled raster values; vertical datum and metre units NOT verified"}
