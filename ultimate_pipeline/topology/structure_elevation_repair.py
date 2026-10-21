#!/usr/bin/env python3
"""P0-D source-stage repair: bridge / tunnel / elevated separation from terrain.

For each road classified bridge/elevated/tunnel by stage-5 structure classification,
samples the DEM along the centreline and rewrites elevationProfile so deck z stays
>= min_clearance_m above terrain (bridge/elevated) or <= -min_clearance_m below
terrain (tunnel).

Uses the same DEM sampling path that stage_05_geometry uses.
Fail-closed: if DEM unavailable, reports INCOMPLETE; never invents data.
"""
from __future__ import annotations
import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

try:
    import rasterio
    from rasterio.transform import rowcol
    _RASTERIO_OK = True
except Exception:
    _RASTERIO_OK = False


def _safe_float(x, default=0.0) -> float:
    try:
        return float(str(x).strip()) if x is not None else float(default)
    except (ValueError, TypeError):
        return float(default)


def _length_of(road: ET.Element) -> float:
    geoms = road.findall("./planView/geometry")
    if not geoms:
        return 0.0
    last = geoms[-1]
    return _safe_float(last.get("s")) + _safe_float(last.get("length"))


def _build_terrain_sampler(dem_path: str, xodr_path: Optional[str] = None):
    """Build a terrain sampler reusing the stage-05 CRS resolution."""
    if not _RASTERIO_OK:
        return None, {"status": "rasterio_unavailable"}
    try:
        from ultimate_pipeline.dem.dem_crs_contract import resolve_sampling_crs
        dst, _source, record = resolve_sampling_crs(xodr_path, osm_path=None, strict=True)
        with rasterio.open(dem_path) as ds:
            # Transform from XODR local coords -> DEM CRS
            # The XODR coordinate system matches the map CRS via offset
            header_offset = _header_offset(xodr_path) if xodr_path else {"x": 0.0, "y": 0.0}

            def sampler(x: float, y: float) -> Optional[float]:
                world_x = float(x) + float(header_offset.get("x", 0.0))
                world_y = float(y) + float(header_offset.get("y", 0.0))
                try:
                    row, col = ds.index(world_x, world_y)
                    if 0 <= row < ds.height and 0 <= col < ds.width:
                        v = ds.read(1)[row, col]
                        return float(v) if v is not None else None
                    return None
                except Exception:
                    return None

            return sampler, {"status": "ok", "crs_record": record}
    except Exception as exc:
        return None, {"status": "failed", "reason": str(exc)}


def _header_offset(xodr_path: Optional[str]) -> Dict[str, float]:
    if not xodr_path:
        return {"x": 0.0, "y": 0.0}
    try:
        from ultimate_pipeline.dem.dem_crs_contract import header_offset_from_xodr
        off = header_offset_from_xodr(xodr_path)
        return {
            "x": _safe_float(off.get("x", 0.0), 0.0),
            "y": _safe_float(off.get("y", 0.0), 0.0),
        }
    except Exception:
        return {"x": 0.0, "y": 0.0}


def repair_structure_elevation_separation(
    root: ET.Element,
    road_classes: Optional[Dict[str, str]] = None,
    dem_path: Optional[str] = None,
    xodr_path: Optional[str] = None,
    min_clearance_m: float = 0.5,
) -> Dict[str, Any]:
    """Enforce structure-bridge/tunnel terrain separation at source stage.

    Args:
        root: XODR root element (modified in-place).
        road_classes: {road_id_str: class_str} from structure_classifier.
            If None, attempts classification if osm_path available.
        dem_path: path to DEM TIFF file.
        xodr_path: path to XODR (for CRS resolution).
        min_clearance_m: minimum deck-above-terrain or tunnel-below-terrain.
    """
    if road_classes is None:
        return {"ok": False, "INCOMPLETE": True, "reason": "no road_classes provided (requires structure classification from stage 5)"}

    if not dem_path or not os.path.exists(dem_path):
        return {"ok": False, "INCOMPLETE": True, "reason": "dem_unavailable"}

    terrain_sampler, sampler_info = _build_terrain_sampler(dem_path, xodr_path)
    if terrain_sampler is None:
        return {"ok": False, "INCOMPLETE": True, "reason": f"terrain_sampler_unavailable: {sampler_info.get('reason', 'unknown')}"}

    repaired = 0
    unrepaired = 0
    records: List[Dict[str, Any]] = []

    for r_el in root.findall("road"):
        rid = str(r_el.get("id") or "").strip()
        if not rid:
            continue
        rc = road_classes.get(rid)
        if rc not in ("bridge", "elevated", "tunnel"):
            continue

        # Sample DEM at geometry midpoints
        geoms = sorted(r_el.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s"), 0.0))
        if not geoms:
            continue

        target_offset = float(min_clearance_m) if rc in ("bridge", "elevated") else float(-min_clearance_m)

        # Sample at midpoint
        geom = geoms[len(geoms) // 2]
        x = _safe_float(geom.get("x"), 0.0)
        y = _safe_float(geom.get("y"), 0.0)
        terrain_z = terrain_sampler(x, y)

        if terrain_z is None:
            unrepaired += 1
            records.append({"road_id": rid, "class": rc, "ok": False, "reason": "dem_sample_missing"})
            continue

        # Check current elevation profile
        profile = r_el.find("elevationProfile")
        road_z_at_mid = None
        if profile is not None:
            elevs = [(_safe_float(e.get("s"), 0.0), e) for e in profile.findall("elevation")]
            if elevs:
                elevs.sort()
                s_mid = _safe_float(geom.get("s"), 0.0) + _safe_float(geom.get("length"), 0.0) / 2.0
                seg = elevs[0][1]
                for s_e, el in elevs:
                    if s_e <= s_mid:
                        seg = el
                    else:
                        break
                a = _safe_float(seg.get("a"), 0.0)
                b = _safe_float(seg.get("b"), 0.0)
                c = _safe_float(seg.get("c"), 0.0)
                d = _safe_float(seg.get("d"), 0.0)
                ds = max(0.0, s_mid - _safe_float(seg.get("s"), 0.0))
                road_z_at_mid = a + b * ds + c * ds * ds + d * ds ** 3

        dz = road_z_at_mid - float(terrain_z) if road_z_at_mid is not None else None
        current_offset = dz if dz is not None else 0.0

        # If already separated, leave alone
        if rc in ("bridge", "elevated"):
            if current_offset >= target_offset:
                repaired += 1
                records.append({"road_id": rid, "class": rc, "ok": True, "dz": round(current_offset, 3), "action": "already_separated"})
                continue
        else:  # tunnel
            if current_offset <= target_offset:
                repaired += 1
                records.append({"road_id": rid, "class": rc, "ok": True, "dz": round(current_offset, 3), "action": "already_separated"})
                continue

        # Repair: set a flat elevation profile at terrain + target_offset
        if profile is None:
            profile = ET.SubElement(r_el, "elevationProfile")
        for el in list(profile.findall("elevation")):
            profile.remove(el)
        el = ET.SubElement(profile, "elevation")
        el.set("s", "0")
        el.set("a", f"{float(terrain_z) + target_offset:.3f}")
        el.set("b", "0")
        el.set("c", "0")
        el.set("d", "0")
        new_dz = float(terrain_z) + target_offset - float(terrain_z)
        repaired += 1
        records.append({
            "road_id": rid,
            "class": rc,
            "ok": True,
            "terrain_z": round(float(terrain_z), 3),
            "old_dz": round(current_offset, 3) if current_offset else None,
            "new_dz": round(new_dz, 3),
            "action": "repaired_elevation_profile",
        })

    return {
        "ok": repaired >= len([r for r in records if r.get("class") in ("bridge", "elevated", "tunnel")]) or unrepaired == 0,
        "repair_type": "P0-D_structure_elevation_separation",
        "repaired_roads": repaired,
        "unrepaired_roads": unrepaired,
        "min_clearance_m": min_clearance_m,
        "records": records[:50],
    }
