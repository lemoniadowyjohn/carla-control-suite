#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-tile FBX generator for CARLA Large-Map cooking (visual/FBX side only).

This module implements the P1/P2 "moderate extension of existing code" laid out
in ``reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md``:
it produces the ``<MapName>_Tile_<x>_<y>.fbx`` files a CARLA Large Map cook
consumes, by **clipping the buildings source per tile** and running the existing,
tested OSM2World -> Blender -> FBX path once per tile.

What this is NOT
----------------
This is *not* an XODR carve. Per the design's decisive finding (DESIGN.md §1-§3),
a CARLA Large Map imports the whole XODR once, unsplit; only the FBX/visual layer
is tiled. ``ultimate_pipeline.tiling.runtime_tile_builder`` solves a different
problem (standalone-OpenDRIVE routing subsets with a 100 m overlap buffer + local
rebasing + junction closure) and is deliberately **not** reused here: its overlap
buffer would double-render buildings at seams, and its local rebasing would break
the single-shared-world-origin invariant that tiled FBX must preserve
(AG05 / UNREAL_COOKING_PARAMETERS.md §10). This module never imports it.

Seam strategy (DESIGN.md §3.2)
------------------------------
**Hard, non-overlapping clip.** Every building is assigned to *exactly one* tile
by the grid cell that contains its **footprint centroid**. This makes the tiling a
true spatial *partition*: a building straddling a grid line is emitted whole in the
tile owning its centroid and simply overhangs the neighbour's cell (which is
correct -- opaque solids at their true world position never z-fight against a
non-existent second copy). This guarantees:

- no building is duplicated into two tiles (no double-render / z-fighting /
  doubled semantic labels),
- no building is dropped from both tiles,
- no building is geometrically severed (we clip the *source*, never the mesh).

The centroid rule is the single trickiest correctness question and is unit-tested
directly (see ``tests/unit/test_tile_fbx_generator.py``).

Coordinate frame (DESIGN.md §2.4)
---------------------------------
The tile grid is defined once in **XODR-local metres** -- the same frame
``runtime_tile_builder`` and the map extent (``map_stats.json``) use. Each building
footprint's WGS84 coordinates are projected to that frame with the *exact* transform
``ultimate_pipeline.enrichment.osm_polygon_loader`` already uses:

    WGS84 (lon, lat) --[+proj=tmerc +datum=WGS84 +units=m +no_defs]--> global metres
    global metres - XODR header offset (x, y) --> XODR-local metres

No new alignment is derived (AG04 forbids re-deriving it); the building-frame
alignment audit already measured median displacement 1.2e-6 m between these two
frames on the pinned artifacts.

Public API
----------
``TileGridSpec``
    Immutable grid parameters (tile size, origin, header offset).

``assign_buildings_to_tiles(buildings, grid)``
    Pure partition function: maps each building to exactly one ``(tx, ty)`` cell by
    centroid. The correctness core; no I/O.

``clip_buildings_to_tile(...)`` / ``write_tile_osm_xml(...)``
    Write one tile's building-bearing OSM-XML (reusing the same negative-id,
    deduplicated-node emission discipline as ``overpass_to_osm_xml``).

``generate_tile_fbx(...)``
    Run the full clip -> OSM2World -> Blender -> FBX -> roundtrip path for one tile,
    emitting ``<MapName>_Tile_<tx>_<ty>.fbx`` and a hash-bound manifest.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pyproj import Transformer

# The FBX-side render path (all already tested; reused verbatim, not reinvented).
from ultimate_pipeline.enrichment.osm2world_runner import OSM2WorldRunner
from ultimate_pipeline.enrichment.blender_runner import BlenderRunner, DEFAULT_BLENDER_EXE
from ultimate_pipeline.enrichment.fbx_roundtrip import run_fbx_roundtrip


# ---------------------------------------------------------------------------
# Coordinate transform: identical convention to
# ultimate_pipeline.enrichment.osm_polygon_loader (bare tmerc global frame).
# Do NOT change this string; roads and buildings must share exactly this frame
# (C29, AG04). See osm_polygon_loader.PROJ_STRING for the load-bearing rationale.
# ---------------------------------------------------------------------------
_PROJ_STRING = "+proj=tmerc +datum=WGS84 +units=m +no_defs"

# (lon, lat) -> global tmerc (x, y) metres. Module-level singletons: pyproj
# Transformer construction is relatively expensive and these are stateless.
_FWD_TRANSFORMER = Transformer.from_crs("EPSG:4326", _PROJ_STRING, always_xy=True)
# global tmerc (x, y) metres -> (lon, lat). Used to express tile windows as
# lat/lon boxes for provenance/debugging.
_INV_TRANSFORMER = Transformer.from_crs(_PROJ_STRING, "EPSG:4326", always_xy=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Grid specification
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TileGridSpec:
    """Immutable CARLA Large-Map tile grid, defined in XODR-local metres.

    A cell ``(tx, ty)`` covers the half-open box
    ``x in [origin_x + tx*tile_size, origin_x + (tx+1)*tile_size)`` and likewise
    for ``y``. Half-open on the upper edge so cell boundaries partition the plane
    with no overlap (a point exactly on a boundary belongs to the higher-index
    cell), which is what makes the centroid assignment a clean partition.

    ``header_offset_xy`` is the XODR ``<offset>`` (global tmerc metres) that maps
    global coordinates to this local frame; it is subtracted after projection.
    For the pinned map-of-record it is ``(832671.676, 5458671.104)``.
    """

    tile_size_m: float
    header_offset_xy: Tuple[float, float]
    # Grid origin in XODR-local metres. Defaults to (0, 0): the pinned map's
    # local extent starts at ~(-9.3, -8.3), so cell index 0 covers the origin
    # and slightly-negative coordinates fall into tx=-1/ty=-1, which is correct
    # and preserved (nothing is silently clamped).
    origin_x: float = 0.0
    origin_y: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.tile_size_m) or self.tile_size_m <= 0.0:
            raise ValueError("tile_size_m must be positive and finite")
        ox, oy = self.header_offset_xy
        if not (math.isfinite(ox) and math.isfinite(oy)):
            raise ValueError("header_offset_xy must be finite")
        if not (math.isfinite(self.origin_x) and math.isfinite(self.origin_y)):
            raise ValueError("grid origin must be finite")

    def cell_index(self, local_x: float, local_y: float) -> Tuple[int, int]:
        """Return the ``(tx, ty)`` cell containing an XODR-local metric point."""
        tx = math.floor((local_x - self.origin_x) / self.tile_size_m)
        ty = math.floor((local_y - self.origin_y) / self.tile_size_m)
        return int(tx), int(ty)

    def cell_bounds_local(self, tx: int, ty: int) -> Dict[str, float]:
        """Half-open local-metre box of cell ``(tx, ty)``."""
        x_min = self.origin_x + tx * self.tile_size_m
        y_min = self.origin_y + ty * self.tile_size_m
        return {
            "x_min": x_min,
            "x_max": x_min + self.tile_size_m,
            "y_min": y_min,
            "y_max": y_min + self.tile_size_m,
        }

    def cell_bounds_wgs84(self, tx: int, ty: int) -> Dict[str, float]:
        """Lat/lon bounding box of cell ``(tx, ty)`` (for provenance/logging).

        The tmerc projection is not axis-aligned with lon/lat in general, so the
        returned box is the *bounding* lon/lat of the four projected corners --
        a superset of the true (slightly rotated) cell. It is used only for
        human-readable provenance, never for assignment (assignment is exact and
        done in the local metric frame).
        """
        local = self.cell_bounds_local(tx, ty)
        ox, oy = self.header_offset_xy
        corners_local = [
            (local["x_min"], local["y_min"]),
            (local["x_max"], local["y_min"]),
            (local["x_min"], local["y_max"]),
            (local["x_max"], local["y_max"]),
        ]
        lons: List[float] = []
        lats: List[float] = []
        for lx, ly in corners_local:
            lon, lat = _INV_TRANSFORMER.transform(lx + ox, ly + oy)
            lons.append(lon)
            lats.append(lat)
        return {
            "lon_min": min(lons),
            "lon_max": max(lons),
            "lat_min": min(lats),
            "lat_max": max(lats),
        }


# ---------------------------------------------------------------------------
# Building model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TileBuilding:
    """One building footprint ready for tile assignment.

    ``rings`` is a list of closed rings; each ring is a list of ``(lon, lat)``
    WGS84 vertices (Overpass "out geom" order). ``tags`` are the OSM tags carried
    onto the emitted way(s). ``source_id`` is the original Overpass element id
    (int) for traceability -- it is *not* re-used as an OSM id in output.
    """

    source_id: str
    source_type: str  # "way" | "relation"
    tags: Dict[str, str]
    rings: Sequence[Sequence[Tuple[float, float]]]

    def outer_vertices_lonlat(self) -> List[Tuple[float, float]]:
        """All vertices across all rings, as (lon, lat)."""
        pts: List[Tuple[float, float]] = []
        for ring in self.rings:
            pts.extend((float(lon), float(lat)) for lon, lat in ring)
        return pts

    def centroid_local(self, grid: TileGridSpec) -> Optional[Tuple[float, float]]:
        """Area-weighted footprint centroid, projected to XODR-local metres.

        Uses the polygon (shoelace) centroid of the largest ring, computed in the
        projected metric frame so it is a true planar centroid. Falls back to the
        vertex mean when the ring is degenerate (zero area / collinear), so every
        building with >=1 finite vertex is assignable (never dropped). Returns
        ``None`` only when the building has no finite vertices at all.
        """
        ox, oy = grid.header_offset_xy
        best_ring_xy: Optional[List[Tuple[float, float]]] = None
        best_area = -1.0
        all_xy: List[Tuple[float, float]] = []
        for ring in self.rings:
            ring_xy: List[Tuple[float, float]] = []
            for lon, lat in ring:
                try:
                    gx, gy = _FWD_TRANSFORMER.transform(float(lon), float(lat))
                except (TypeError, ValueError):
                    continue
                if not (math.isfinite(gx) and math.isfinite(gy)):
                    continue
                pt = (gx - ox, gy - oy)
                ring_xy.append(pt)
                all_xy.append(pt)
            area = _abs_shoelace_area(ring_xy)
            if area > best_area:
                best_area = area
                best_ring_xy = ring_xy
        if best_ring_xy and best_area > 0.0:
            c = _polygon_centroid(best_ring_xy)
            if c is not None:
                return c
        if all_xy:
            mx = sum(p[0] for p in all_xy) / len(all_xy)
            my = sum(p[1] for p in all_xy) / len(all_xy)
            return (mx, my)
        return None


def _abs_shoelace_area(coords: Sequence[Tuple[float, float]]) -> float:
    if len(coords) < 3:
        return 0.0
    a = 0.0
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) * 0.5


def _polygon_centroid(coords: Sequence[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """Shoelace polygon centroid. Returns None for degenerate (zero-area) rings."""
    if len(coords) < 3:
        return None
    cx = 0.0
    cy = 0.0
    signed_area = 0.0
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        signed_area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    signed_area *= 0.5
    if abs(signed_area) < 1e-12:
        return None
    factor = 1.0 / (6.0 * signed_area)
    return (cx * factor, cy * factor)


# ---------------------------------------------------------------------------
# Loading buildings from the pinned Overpass-JSON source
# ---------------------------------------------------------------------------
def load_buildings_from_overpass_json(overpass_json_path: str) -> List[TileBuilding]:
    """Read an Overpass "out geom" JSON building export into TileBuilding objects.

    Mirrors the format assumptions of
    ``ultimate_pipeline.enrichment.overpass_to_osm_xml`` and
    ``osm_polygon_loader``: ``way`` elements carry an embedded ``geometry`` array
    of ``{lat, lon}``; ``relation`` (multipolygon building) elements carry
    ``members`` each with their own embedded ``geometry``. Only the outer rings
    are kept (inner/courtyard rings are a documented accepted over-fill; OSM2World
    renders a building volume from the outer ring alone).
    """
    src = Path(overpass_json_path)
    if not src.exists():
        raise FileNotFoundError(f"Overpass JSON source not found: {overpass_json_path}")
    with open(src, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)
    elements = data.get("elements")
    if elements is None:
        raise ValueError(
            f"{overpass_json_path} has no top-level 'elements' list -- "
            "not Overpass 'out geom' JSON shaped input."
        )

    buildings: List[TileBuilding] = []
    for elem in elements:
        etype = elem.get("type")
        if etype == "way":
            ring = _geom_to_lonlat(elem.get("geometry"))
            if len(ring) < 3:
                continue
            buildings.append(
                TileBuilding(
                    source_id=str(elem.get("id")),
                    source_type="way",
                    tags=dict(elem.get("tags") or {}),
                    rings=[ring],
                )
            )
        elif etype == "relation":
            rings: List[List[Tuple[float, float]]] = []
            for member in elem.get("members") or []:
                if member.get("type") != "way":
                    continue
                if member.get("role") not in ("outer", "", None):
                    continue
                ring = _geom_to_lonlat(member.get("geometry"))
                if len(ring) >= 3:
                    rings.append(ring)
            if not rings:
                continue
            buildings.append(
                TileBuilding(
                    source_id=str(elem.get("id")),
                    source_type="relation",
                    tags=dict(elem.get("tags") or {}),
                    rings=rings,
                )
            )
    return buildings


def _geom_to_lonlat(geometry: Any) -> List[Tuple[float, float]]:
    ring: List[Tuple[float, float]] = []
    for pt in geometry or []:
        if not pt:
            continue
        try:
            ring.append((float(pt["lon"]), float(pt["lat"])))
        except (KeyError, TypeError, ValueError):
            continue
    return ring


# ---------------------------------------------------------------------------
# THE PARTITION: assign each building to exactly one tile by centroid.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TileAssignment:
    """Result of partitioning buildings across the grid."""

    grid: TileGridSpec
    # (tx, ty) -> list of buildings whose centroid falls in that cell
    tiles: Dict[Tuple[int, int], List[TileBuilding]]
    # buildings with no finite geometry at all (cannot be placed); reported, not
    # silently dropped, so the partition is fully accounted for.
    unplaceable: List[TileBuilding] = field(default_factory=list)

    def total_placed(self) -> int:
        return sum(len(v) for v in self.tiles.values())

    def occupied_cells(self) -> List[Tuple[int, int]]:
        return sorted(self.tiles.keys())


def assign_buildings_to_tiles(
    buildings: Sequence[TileBuilding],
    grid: TileGridSpec,
) -> TileAssignment:
    """Partition buildings across grid cells by footprint centroid.

    Correctness contract (unit-tested):
      * Every building with finite geometry lands in *exactly one* cell.
      * A building whose footprint straddles a grid boundary is placed by its
        centroid only -- never in both neighbours, never in neither.
      * placed + unplaceable == len(buildings)  (nothing vanishes).
    """
    tiles: Dict[Tuple[int, int], List[TileBuilding]] = {}
    unplaceable: List[TileBuilding] = []
    for b in buildings:
        c = b.centroid_local(grid)
        if c is None:
            unplaceable.append(b)
            continue
        cell = grid.cell_index(c[0], c[1])
        tiles.setdefault(cell, []).append(b)
    return TileAssignment(grid=grid, tiles=tiles, unplaceable=unplaceable)


# ---------------------------------------------------------------------------
# Emit one tile's building-bearing OSM XML (source-level clip, whole buildings).
# ---------------------------------------------------------------------------
# Reuse the exact id-space discipline of overpass_to_osm_xml: negative synthetic
# node ids from -1 downward, way ids from a far-negative base, deduplicated nodes.
_COORD_PRECISION = 7
_WAY_ID_BASE = -1_000_000_000


def _round_coord(lat: float, lon: float) -> Tuple[float, float]:
    return (round(float(lat), _COORD_PRECISION), round(float(lon), _COORD_PRECISION))


def write_tile_osm_xml(
    buildings: Sequence[TileBuilding],
    output_osm_path: str,
) -> Dict[str, int]:
    """Serialize the buildings assigned to one tile as a self-contained OSM XML.

    Each building's *whole* footprint is written (never clipped mid-polygon), so
    there are no cut edges at tile seams. Nodes are deduplicated by rounded
    coordinate (OSM 1e-7 precision) exactly as ``overpass_to_osm_xml`` does, so
    shared corners collapse to one node (avoids OSM2World duplicate-point
    degeneracies). Ids are negative synthetic, matching the merge-safe convention.
    """
    coord_to_id: Dict[Tuple[float, float], int] = {}
    nodes: List[Tuple[int, float, float]] = []  # (id, lat, lon)
    next_node_id = -1

    def _node(lon: float, lat: float) -> int:
        nonlocal next_node_id
        key = _round_coord(lat, lon)
        existing = coord_to_id.get(key)
        if existing is not None:
            return existing
        nid = next_node_id
        next_node_id -= 1
        coord_to_id[key] = nid
        nodes.append((nid, key[0], key[1]))
        return nid

    way_records: List[Tuple[int, List[int], Dict[str, str]]] = []
    next_way_id = _WAY_ID_BASE

    def _new_way_id() -> int:
        nonlocal next_way_id
        wid = next_way_id
        next_way_id -= 1
        return wid

    ways_written = 0
    for b in buildings:
        for ring in b.rings:
            node_ids = [_node(lon, lat) for (lon, lat) in ring]
            if len(node_ids) < 3:
                continue
            if node_ids[0] != node_ids[-1]:
                node_ids.append(node_ids[0])
            way_records.append((_new_way_id(), node_ids, dict(b.tags)))
            ways_written += 1

    root = ET.Element("osm", {"version": "0.6", "generator": "tile_fbx_generator.py"})
    for nid, lat, lon in nodes:
        ET.SubElement(
            root,
            "node",
            {"id": str(nid), "lat": f"{lat:.7f}", "lon": f"{lon:.7f}", "visible": "true"},
        )
    for wid, node_ids, tags in way_records:
        way_el = ET.SubElement(root, "way", {"id": str(wid), "visible": "true"})
        for nid in node_ids:
            ET.SubElement(way_el, "nd", {"ref": str(nid)})
        for k, v in tags.items():
            if v is None:
                continue
            ET.SubElement(way_el, "tag", {"k": str(k), "v": str(v)})

    out_path = Path(output_osm_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return {
        "buildings": len(buildings),
        "nodes_written": len(nodes),
        "ways_written": ways_written,
    }


def tile_fbx_name(map_name: str, tx: int, ty: int) -> str:
    """CARLA Large-Map tile FBX name: ``<MapName>_Tile_<x>_<y>.fbx``."""
    return f"{map_name}_Tile_{tx}_{ty}.fbx"


# OSM2World config: clutter only, roads owned by CARLA/OpenDRIVE (AG03A). Mirrors
# the phase_j / DEFAULT_CONFIG convention already used elsewhere in this codebase.
_OSM2WORLD_CONFIG_TEXT = """# OSM2World configuration (tile FBX generation; buildings/clutter only)
# Roads/rail/aeroway/parking are owned by the CARLA/OpenDRIVE map (AG03A).
createTerrain=false
renderUnderground=false
useBuildingColors=true
implicitWindowImplementation=NONE
explicitWindowImplementation=NONE
excludeWorldModule=RoadModule;RailwayModule;AerowayModule;ParkingModule
treesPerSquareMeter=0.02
defaultTreeHeight=8
defaultTreeHeightForest=12
lodDistances=100,500,2000
"""


@dataclass
class TileFbxResult:
    """Outcome of generating one tile's FBX."""

    status: str  # "ok" | "empty" | "failed"
    tile_index: Tuple[int, int]
    fbx_name: str
    reason: str = ""
    building_count: int = 0
    osm_path: str = ""
    obj_path: str = ""
    fbx_path: str = ""
    fbx_bytes: int = 0
    fbx_sha256: str = ""
    objects_total: int = 0
    vertices_total: int = 0
    faces_total: int = 0
    roundtrip_ok: Optional[bool] = None
    roundtrip_verdict: str = ""
    osm2world_sec: float = 0.0
    blender_sec: float = 0.0
    roundtrip_sec: float = 0.0
    total_sec: float = 0.0
    manifest_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "tile_index": list(self.tile_index),
            "fbx_name": self.fbx_name,
            "reason": self.reason,
            "building_count": self.building_count,
            "osm_path": self.osm_path,
            "obj_path": self.obj_path,
            "fbx_path": self.fbx_path,
            "fbx_bytes": self.fbx_bytes,
            "fbx_sha256": self.fbx_sha256,
            "objects_total": self.objects_total,
            "vertices_total": self.vertices_total,
            "faces_total": self.faces_total,
            "roundtrip_ok": self.roundtrip_ok,
            "roundtrip_verdict": self.roundtrip_verdict,
            "osm2world_sec": self.osm2world_sec,
            "blender_sec": self.blender_sec,
            "roundtrip_sec": self.roundtrip_sec,
            "total_sec": self.total_sec,
            "manifest_path": self.manifest_path,
        }


def _inventory_totals(manifest: Dict[str, Any]) -> Tuple[int, int, int]:
    """Sum objects/vertices/faces from a blender conversion manifest inventory."""
    objs = manifest.get("objects") or []
    objects_total = manifest.get("objects_total", len(objs))
    vertices = sum(int(o.get("vertices", 0)) for o in objs)
    faces = sum(int(o.get("faces", 0)) for o in objs)
    return int(objects_total), vertices, faces


def generate_tile_fbx(
    *,
    buildings: Sequence[TileBuilding],
    tile_index: Tuple[int, int],
    map_name: str,
    output_dir: str,
    osm2world_home: str,
    blender_exe: Optional[str] = None,
    run_roundtrip: bool = True,
    osm2world_timeout_sec: int = 1800,
    blender_timeout_sec: int = 900,
    source_provenance: Optional[Dict[str, Any]] = None,
) -> TileFbxResult:
    """Produce one ``<MapName>_Tile_<x>_<y>.fbx`` from its assigned buildings.

    Steps (all reuse tested components; this is orchestration, not new geometry):
      1. Write the tile's whole-building OSM XML (source-level clip).
      2. OSM2World -> OBJ  (``OSM2WorldRunner``).
      3. Blender OBJ -> FBX (``BlenderRunner``), named per CARLA convention.
      4. FBX roundtrip integrity check in a clean Blender (``run_fbx_roundtrip``).
      5. Write a hash-bound manifest sidecar.

    Emits at the shared world origin (no per-tile re-centering): the buildings keep
    their true global positions because ``write_tile_osm_xml`` preserves each
    footprint's real lon/lat and OSM2World projects to the same global frame.
    """
    tx, ty = tile_index
    fbx_name = tile_fbx_name(map_name, tx, ty)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{map_name}_Tile_{tx}_{ty}"
    result = TileFbxResult(status="failed", tile_index=(tx, ty), fbx_name=fbx_name,
                           building_count=len(buildings))
    started = time.time()

    if not buildings:
        result.status = "empty"
        result.reason = "no buildings assigned to this tile"
        result.total_sec = round(time.time() - started, 3)
        return result

    # 1. source-level clip -> tile OSM XML
    osm_path = out_dir / f"{stem}.osm"
    clip_stats = write_tile_osm_xml(buildings, str(osm_path))
    result.osm_path = str(osm_path)
    if clip_stats["ways_written"] == 0:
        result.status = "empty"
        result.reason = "clip produced 0 ways"
        result.total_sec = round(time.time() - started, 3)
        return result

    # 2. OSM2World -> OBJ
    config_path = out_dir / f"{stem}.osm2world.properties"
    config_path.write_text(_OSM2WORLD_CONFIG_TEXT, encoding="ascii", newline="\n")
    import os
    os.environ["OSM2WORLD_OUTPUTS"] = "obj"
    o2w_started = time.time()
    o2w = OSM2WorldRunner(
        osm_path=str(osm_path),
        output_dir=str(out_dir),
        osm2world_home=osm2world_home,
        timeout_sec=osm2world_timeout_sec,
        config_path=str(config_path),
        name_prefix=stem,
    ).run()
    result.osm2world_sec = round(time.time() - o2w_started, 3)
    obj_path = out_dir / f"{stem}.obj"
    if o2w.status not in ("ok", "cached") or not obj_path.exists():
        result.status = "failed"
        result.reason = f"OSM2World status={o2w.status}: {o2w.reason}"
        result.total_sec = round(time.time() - started, 3)
        return result
    result.obj_path = str(obj_path)

    # 3. Blender OBJ -> FBX
    blender_exe_path = blender_exe or str(DEFAULT_BLENDER_EXE)
    b_started = time.time()
    bres = BlenderRunner(
        obj_path=str(obj_path),
        output_dir=str(out_dir),
        blender_exe=blender_exe_path,
        timeout_sec=blender_timeout_sec,
        name_prefix=stem,
    ).run()
    result.blender_sec = round(time.time() - b_started, 3)
    fbx_path = out_dir / f"{stem}.fbx"
    if bres.status != "ok" or not fbx_path.exists():
        result.status = "failed"
        result.reason = f"Blender status={bres.status}: {bres.reason}"
        result.total_sec = round(time.time() - started, 3)
        return result
    result.fbx_path = str(fbx_path)
    result.fbx_bytes = fbx_path.stat().st_size
    result.fbx_sha256 = _sha256(fbx_path)
    manifest = bres.manifest or {}
    objects_total, vertices_total, faces_total = _inventory_totals(manifest)
    result.objects_total = objects_total
    result.vertices_total = vertices_total
    result.faces_total = faces_total

    # 4. FBX roundtrip integrity (reuse existing machinery, do not reinvent)
    if run_roundtrip and Path(blender_exe_path).exists():
        rt_started = time.time()
        ok, report = run_fbx_roundtrip(
            fbx_path, out_dir, Path(blender_exe_path),
            source_manifest=manifest, timeout_sec=blender_timeout_sec,
        )
        result.roundtrip_sec = round(time.time() - rt_started, 3)
        result.roundtrip_ok = ok
        result.roundtrip_verdict = report.get("comparison", {}).get(
            "verdict", report.get("error", "UNKNOWN"))
    else:
        result.roundtrip_ok = None
        result.roundtrip_verdict = "SKIPPED"

    result.status = "ok"
    result.total_sec = round(time.time() - started, 3)

    # 5. hash-bound manifest sidecar
    manifest_path = out_dir / f"{stem}.tile_fbx.json"
    manifest_doc = {
        "schema_version": 1,
        "artifact_type": "carla_large_map_tile_fbx",
        "status": result.status,
        "map_name": map_name,
        "tile_index": [tx, ty],
        "fbx_name": fbx_name,
        "seam_strategy": "hard_nonoverlapping_clip_centroid_assignment",
        "clip": clip_stats,
        "fbx": {
            "path": str(fbx_path),
            "sha256": result.fbx_sha256,
            "bytes": result.fbx_bytes,
            "objects_total": objects_total,
            "vertices_total": vertices_total,
            "faces_total": faces_total,
        },
        "roundtrip": {
            "ok": result.roundtrip_ok,
            "verdict": result.roundtrip_verdict,
        },
        "timing_sec": {
            "osm2world": result.osm2world_sec,
            "blender": result.blender_sec,
            "roundtrip": result.roundtrip_sec,
            "total": result.total_sec,
        },
        "source_provenance": source_provenance or {},
        "claim_boundary": (
            "Offline FBX generation only. This tile has NOT been imported by a "
            "UE4/UE5 Editor or cooked; runtime streaming/seam behavior is "
            "UNCONFIRMED until the live UE4 track runs."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.manifest_path = str(manifest_path)
    return result
