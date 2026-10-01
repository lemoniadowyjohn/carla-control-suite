"""Compute authoritative placement transforms for all tiles from existing artifacts.

This script reads each tile's source OSM and exported OBJ, computes the placement
translation T = C_s_local - C_v_local (source OSM bbox center minus exported mesh
bbox center in local frame), and updates the tile manifest with a `placement`
field. This is a ONE-TIME retroactive binding for the existing cooked tiles.
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from pyproj import Transformer

FWD = Transformer.from_crs(
    "EPSG:4326", "+proj=tmerc +datum=WGS84 +units=m +no_defs", always_xy=True
)
OFF = (832671.676, 5458671.104)
BASE = Path(
    r"F:\p0-coord-frame-tile-placement-20261001"
    r"\reports\production_readiness\20260924T100614Z_FULL_GRID_TILE_FBX_COOK\artifacts"
)
CONTRACT_VERSION = "1.0.0"
MAP_SHA256 = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"


def src_bbox_center(p):
    xs, ys = [], []
    for n in ET.parse(p).getroot().iter("node"):
        try:
            la, lo = float(n.get("lat")), float(n.get("lon"))
        except (TypeError, ValueError):
            continue
        x, y = FWD.transform(lo, la)
        xs.append(x - OFF[0])
        ys.append(y - OFF[1])
    if not xs:
        return None
    return np.array([(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0])


def obj_bbox_center(p):
    xs, ys = [], []
    for line in p.read_text(errors="ignore").splitlines():
        if line.startswith("v "):
            a = line.split()
            xs.append(float(a[1]))
            ys.append(float(a[3]))
    if not xs:
        return None
    return np.array([(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0])


def obj_sha256(p):
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def osm_sha256(p):
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


print("Computing authoritative placement transforms for all 20 tiles...")
placements = []
for tile in sorted(BASE.iterdir()):
    if not tile.is_dir():
        continue
    tx, ty = tile.name.split("_")[1:]
    osm_p = tile / f"Ingolstadt_Tile_{tx}_{ty}.osm"
    obj_p = tile / f"Ingolstadt_Tile_{tx}_{ty}.obj"
    fbx_p = tile / f"Ingolstadt_Tile_{tx}_{ty}.fbx"
    manifest_p = tile / f"Ingolstadt_Tile_{tx}_{ty}.tile_fbx.json"

    if not (osm_p.exists() and obj_p.exists() and fbx_p.exists() and manifest_p.exists()):
        print(f"  {tile.name}: missing artifacts, skipping")
        continue

    C_s = src_bbox_center(osm_p)
    C_v = obj_bbox_center(obj_p)
    if C_s is None or C_v is None:
        print(f"  {tile.name}: empty geometry, skipping")
        continue

    T = C_s - C_v  # translation from mesh local origin to shared local frame

    # Load manifest
    with manifest_p.open("r", encoding="utf-8") as f:
        m = json.load(f)

    # Compute binding hashes
    osm_sha = osm_sha256(osm_p)
    fbx_sha = m["fbx"]["sha256"]

    # Add placement field
    m["placement"] = {
        "schema_version": CONTRACT_VERSION,
        "map_of_record_sha256": MAP_SHA256,
        "tile_index": [int(tx), int(ty)],
        "source_osm_sha256": osm_sha,
        "exported_fbx_sha256": fbx_sha,
        "source_frame": "NATIVE",
        "target_frame": "LOCAL",
        "translation_local_m": [float(T[0]), float(T[1])],
        "translation_bbox_center_source_local_m": [float(C_s[0]), float(C_s[1])],
        "translation_bbox_center_exported_local_m": [float(C_v[0]), float(C_v[1])],
        "authority": "source_osm_bbox_center_minus_exported_mesh_bbox_center",
        "notes": "Derived from source OSM node bbox and exported OBJ bbox. OSM2World auto-centers on exported mesh bbox; this records the translation needed to place the auto-centered mesh at the source footprint bbox center. Wall thickness causes irreducible offset vs true footprint geometry (see TILE_ORIGIN_ROOT_CAUSE.json)."
    }

    # Write updated manifest
    with manifest_p.open("w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)

    placements.append({
        "tile": tile.name,
        "T": [float(T[0]), float(T[1])],
        "C_s": [float(C_s[0]), float(C_s[1])],
        "C_v": [float(C_v[0]), float(C_v[1])]
    })
    print(f"  {tile.name}: T=({T[0]:.2f}, {T[1]:.2f}) C_s=({C_s[0]:.2f}, {C_s[1]:.2f}) C_v=({C_v[0]:.2f}, {C_v[1]:.2f})")

print(f"\nUpdated {len(placements)} tile manifests with placement field.")