# Tile-Based Per-Tile FBX Generation + Densest-Tile Cook Probe

- **Run ID:** `20260915T171346Z_TILE_BASED_FBX_GENERATION_PROBE`
- **Branch:** `feature/tile-based-fbx-generation-v1-20260915`
- **Base:** `integration/session-batch1-20260912` @ `97c8ee81`
- **Implements:** P1/P2 ("moderate extension of existing code") of
  `reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md`.
- **Status:** OFFLINE FBX GENERATION ONLY. No UE4/UE5 Editor was run (none exists on
  this machine). Runtime streaming/seam behavior remains **[UNCONFIRMED — needs live UE4 Editor]**.

This directory documents (a) a new per-tile FBX generator module, (b) its
boundary-building assignment logic, and (c) a **real** go/no-go cook of the single
densest 1 km tile with measured numbers.

---

## 1. What was built

**Module:** `ultimate_pipeline/tiling/tile_fbx_generator.py`
**Tests:** `tests/unit/test_tile_fbx_generator.py` (15 tests, all green)
**Probe runner:** `tools/probe_tile_fbx_densest.py`

The module produces the `<MapName>_Tile_<x>_<y>.fbx` files a CARLA **Large Map**
cook consumes. It follows the design's decisive findings exactly:

- **FBX side only.** It never carves the XODR. The whole 149 MB map-of-record XODR
  is imported once, unsplit, by CARLA; only the visual/FBX layer is tiled. The
  module does **not** import `runtime_tile_builder.py` — that solves a different
  problem (standalone-OpenDRIVE routing subsets with a 100 m overlap buffer +
  local rebasing + junction closure), and both its overlap buffer (would
  double-render buildings) and its local rebasing (would break the single shared
  world origin) are actively wrong for a Large-Map cook.
- **Clip the source, not the mesh.** Each tile's FBX is produced by clipping the
  *buildings source* to the tile and running the existing, tested
  OSM2World → Blender → FBX path (`OSM2WorldRunner`, `BlenderRunner`,
  `run_fbx_roundtrip` — all reused verbatim). No FBX/mesh boolean-clip dependency
  is introduced. Buildings are always rendered whole; no seam ever severs a mesh.
- **Single shared world origin.** The clip preserves each footprint's true WGS84
  position and OSM2World projects through the same global frame, so tiles line up
  by construction with no per-tile re-centering.

### Verification of the design's claims against current code (done before building)

| Claim | Verified |
|---|---|
| `clip_osm_window()` exists at `ultimate_pipeline/tools/phase_j_osm2world_blender.py` | YES — read in full. **Caveat:** its way-keep rule is `all(node in window)` (corner-based, drops any way with a vertex outside), *not* a centroid partition. So it was **not** reused directly; a purpose-built centroid partition was written instead (see §2). |
| Overpass-JSON→OSM-XML machinery in `overpass_to_osm_xml.py` | YES — read in full; its negative-id / dedup-node discipline is mirrored in `write_tile_osm_xml`. |
| OSM2World→OBJ→FBX→roundtrip path is current and tested | YES — `osm2world_runner.py`, `blender_runner.py`, `fbx_roundtrip.py` all read and reused unchanged. |
| Coordinate frame: bare tmerc + subtract XODR header offset | YES — matches `osm_polygon_loader.PROJ_STRING` and header offset `(832671.676, 5458671.104)`. Roundtrip verified to machine precision. |
| OSM2World jar + Blender 4.3 present on machine | YES — jar at `carla_governed/OSM2World-latest-bin/OSM2World.jar` (untracked binary), Blender at `E:\Program Files\Blender Foundation\Blender 4.3\blender.exe`. |

---

## 2. Boundary-building assignment logic (the load-bearing correctness question)

**Rule: each building is assigned to exactly one tile — the grid cell containing
its footprint centroid.** This makes the tiling a true spatial *partition*, not a
set of overlapping windows.

Implementation (`assign_buildings_to_tiles` + `TileBuilding.centroid_local`):

1. Project every footprint vertex WGS84→global tmerc→subtract header offset →
   XODR-local metres (the same frame the grid is defined in).
2. Compute the **area-weighted shoelace polygon centroid** of the building's
   largest ring (true planar centroid, not a naive vertex mean). Degenerate
   (zero-area/collinear) rings fall back to the vertex mean so no building with
   ≥1 finite vertex is ever dropped.
3. `cell_index = (floor((x-origin)/tile_size), floor((y-origin)/tile_size))`.
   Cells are **half-open** `[k·s, (k+1)·s)`, so a point exactly on a boundary
   belongs to the higher-index cell — a clean, deterministic tie-break.

Why centroid and not "any vertex intersects": a building straddling a grid line
is rendered whole inside its centroid's tile and merely overhangs the neighbour's
cell. That is correct — opaque solids at their true world position never z-fight
against a non-existent second copy. An "any-vertex" rule would emit the building
into *both* tiles (double-render, z-fighting, doubled semantic labels — corrosive
for a perception pipeline).

### Correctness contract (directly unit-tested)

- `test_building_straddling_boundary_lands_in_exactly_one_tile` — a footprint that
  physically crosses a boundary is placed in exactly one cell (its centroid's).
- `test_two_buildings_sharing_a_boundary_wall_go_to_different_tiles` — proves the
  seam is a partition, not a lump-everything-together bucket.
- `test_centroid_not_any_vertex_intersection` — a building with heavy mass in
  tx=0 and a spur poking into tx=1 stays in tx=0; would fail under an any-vertex
  rule.
- `test_unplaceable_building_reported_not_dropped` — geometry-less buildings are
  surfaced in `unplaceable`, never silently lost: **placed + unplaceable == total**.
- `test_partition_is_exhaustive_and_disjoint` — every building appears exactly
  once across all cells.
- Plus grid-math (floor division, negative coords not clamped, half-open
  boundaries), whole-building OSM emission (closed rings, negative ids, shared
  corners deduplicated, multi-ring relations), and naming-convention tests.

**On the real pinned source** (`test_loads_all_buildings_and_partitions_them`):
all 5,712 buildings load, partition disjointly across 20 occupied cells, no id in
two cells, densest cell == `(6, 8)` — matching the independent probe.

---

## 3. The go/no-go probe: real cook of the densest 1 km tile

Run: `python tools/probe_tile_fbx_densest.py` (this run). Machine-readable output:
`PROBE_RESULT.json`; per-tile manifest: `artifacts/Ingolstadt_Tile_6_8.tile_fbx.json`.

### Densest-tile selection (measured, this run)

The design doc's probe center (7195, 6796) was chosen by **road** count. For the
FBX side the relevant cost driver is **building** count (DESIGN.md §4.5: FBX/
building triangle count dominates cook time). Partitioning the real source by
building centroid, the densest 1 km cell is **`(6, 8)`** (local box
x∈[6000,7000) m, y∈[8000,9000) m), not the road-based center — a meaningful
refinement. Top cells:

| tile (tx,ty) | buildings |
|---|---|
| **(6, 8)** | **626** |
| (7, 8) | 573 |
| (8, 8) | 493 |
| (7, 9) | 429 |
| (7, 7) | 411 |
| (8, 7) | 409 |
| (6, 7) | 395 |
| (9, 9) | 395 |
| (8, 9) | 353 |
| (7, 6) | 326 |

20 occupied cells hold all 5,712 buildings; the top-10 hold 4,410. The city core
is a tight cluster — most of the 210-tile grid is empty periphery (confirming the
design's non-uniform-density finding).

### Real cook numbers (tile `Ingolstadt_Tile_6_8.fbx`)

| Metric | Value |
|---|---|
| Buildings assigned | **626** |
| FBX objects (meshes) | **636** |
| Vertices | **10,112** |
| Faces | **14,031** |
| FBX file size | **1,631,436 bytes (~1.60 MB)** |
| FBX sha256 | `12b141acbcff6c8f296e871cf95ec39aaf646c4bb21457cef0e658304915b8a0` |
| **FBX roundtrip integrity** | **`ROUNDTRIP_PASS`** (re-imported in a clean second Blender; object/vertex/face/material/bounds all preserved) |
| OSM2World (source→OBJ) | 3.70 s |
| Blender (OBJ→FBX) | 5.59 s |
| Roundtrip re-import | 3.22 s |
| **Total wall-clock** | **12.59 s** |

(Object count 636 > building count 626 because OSM2World splits some
multi-material buildings into sub-meshes — expected, not a partition error.)

### Go/no-go verdict (FBX side)

**GO for the FBX-generation layer.** The densest 1 km tile renders whole, passes
the FBX roundtrip integrity check, and cooks in ~13 s at ~1.6 MB. Since (6,8) is
the heaviest cell and every other cell is lighter, this one probe bounds the whole
grid: the offline per-tile FBX layer is comfortable at 1000 m, no 500 m fallback
needed for the FBX side. This is the FBX-side half of the design's §4.5 decision
rule; the **UE4-cook** half (memory/time inside a live UE4.26 Editor) remains
`[UNCONFIRMED — needs live UE4 Editor]` and is a separate, still-blocked track.

---

## 4. Claim boundary

This work is offline FBX generation + measurement only. It changes no
map-of-record, starts no UE4/UE5 process, and cooks nothing inside Unreal. The FBX
was produced and integrity-checked entirely on the Blender/OSM2World path. Every
statement about how a *cooked* tiled map behaves at runtime (UE cook time/memory,
seam rendering, streaming, label cleanliness) is **[UNCONFIRMED — needs live UE4
Editor]** and cannot be closed until the separate UE4-build track completes.

Heavy reproducible artifacts (`.fbx`/`.obj`/`.osm`) are gitignored under
`artifacts/`; the small JSON manifests, logs, and this document are tracked as
evidence. Regenerate the binaries with `python tools/probe_tile_fbx_densest.py`.

---

## Appendix — file map

- `ultimate_pipeline/tiling/tile_fbx_generator.py` — the generator (grid spec,
  centroid partition, whole-building OSM emission, `generate_tile_fbx` driver).
- `tests/unit/test_tile_fbx_generator.py` — 15 unit tests (boundary assignment
  focus).
- `tools/probe_tile_fbx_densest.py` — the probe runner.
- `PROBE_RESULT.json` — machine-readable probe output (density profile + result).
- `artifacts/Ingolstadt_Tile_6_8.tile_fbx.json` — per-tile hash-bound manifest.
- `artifacts/*.log`, `artifacts/*_status.json`, `artifacts/*_manifest.json` —
  OSM2World/Blender/roundtrip provenance.
