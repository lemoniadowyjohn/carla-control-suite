# LARGE_MAP_PACKAGE_CONTRACT_AUDIT — CARLA Large Map Package Architecture

**Date:** 2026-09-24T (O2 — Large-Map Package Contract Audit)  
**Baseline:** `2e7571269bbe7705595e50ae608de741b2e256c6` (`integration/production-large-map-20260918`) + O1 provenance chain (`o1-cook-provenance-chain` `f7934c13`)  
**Auditor:** O2 read-only inspection of `ultimate_pipeline/tiling/large_map_package.py`, `ultimate_pipeline/tiling/tile_fbx_generator.py`, `scripts/cook_full_grid_tiles.py`, `tools/stage_large_map_import_package.py`, `reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md`  
**Map-of-record:** `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` (SHA `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`, 149799632 bytes, frame `rebased-to-local (dx=832671.676 dy=5458671.104)`) — via `verify_pinned_map("auto_map_of_record")`  
**Tile grid:** `TileGridSpec(tile_size_m=1000.0, header_offset_xy=(832671.676, 5458671.104), origin=(0,0))` — 1000 m, 14×15 = 210 cells, ~30.6 buildings/km², 5712 buildings (verified `COOK_RESULTS.json` buildings_source `f3e820...`)

---

## 1. Current Implementation

**Generator:** `ultimate_pipeline/tiling/large_map_package.py:286` `stage_large_map_package` + `tools/stage_large_map_import_package.py:59` `main`

- **Inputs:** One authoritative whole-map `.xodr` (pinned, `verify_pinned_map`) + N tile FBX paths (`<MapName>_Tile_<x>_<y>.fbx`) produced by `ultimate_pipeline/tiling/tile_fbx_generator.py:1037` `generate_tile_fbx` (per-tile clipped buildings source → OSM2World → Blender → FBX).
- **Staging output:** `Import/<PackageName>/` flat layout exactly as CARLA `Import.py` expects (`DESIGN.md §1.1, §5`):
  ```
  Import/
    Ingolstadt/
      Ingolstadt.xodr               # single whole-map XODR (never split)
      Ingolstadt_Tile_6_6.fbx       # one per non-empty 1000 m cell (CARLA naming)
      Ingolstadt_Tile_6_7.fbx
      ...
      package.json                  # descriptor
      Ingolstadt.json               # byte-identical alias of package.json (both conventions)
      Ingolstadt.large_map_package.json  # hash-bound manifest sidecar (O1 provenance)
  ```
  `_copy_file` uses `shutil.copy2` (never hardlink) so staged artifact is independent of source mutation (P0-C).

- **Descriptor:** `PackageDescriptor` → `build_package_json` emits `{"maps":[{"name","xodr":"./Ingolstadt.xodr","use_carla_materials","tile_size":1000.0,"tiles":["./Ingolstadt_Tile_*.fbx"]}],"props":[]}` plus O1 extension `xodr_sha256` (CARLA ignores unknown fields).

- **Tile FBX generation:** `TileGridSpec` + `assign_buildings_to_tiles` (centroid rule) → `write_tile_osm_xml` (whole buildings, never mesh-cut) → `OSM2WorldRunner` with config `createTerrain=false, excludeWorldModule=RoadModule;RailwayModule;AerowayModule;ParkingModule` → `BlenderRunner` → `run_fbx_roundtrip` → hash-bound `*.tile_fbx.json` sidecar (`source_provenance.map_of_record_sha256`, `fbx.sha256`).

- **Validation gate:** `validate_staged_package` (offline pre-cook gate, DESIGN.md §5 ext 4) checks: one `package.json`, `xodr` exists + SHA, every `tiles[]` exists + naming ` _Tile_<x>_<y>.fbx`, no duplicates, no stray `_Tile_*.fbx` not declared. O1 adds: descriptor `xodr_sha256` matches staged XODR, sidecar `xodr.sha256` matches, per-tile manifest `source_provenance.map_of_record_sha256` matches staged XODR, no mixed generations, missing provenance fails closed. Sorting is deterministic by `(tx,ty)`, never by `mtime`.

**Existing cooked evidence:** `reports/production_readiness/20260915T180446Z_FULL_GRID_TILE_FBX_COOK/COOK_RESULTS.json` — 20 tiles attempted, source `map_of_record 2ca342d8...` (stale vs current `370abbbb`), per-tile `tile_fbx.json` with `source_provenance.map_of_record_sha256` and `fbx.sha256`.

---

## 2. Compliant Fields

| Requirement (O2) | Implementation | Evidence | Verdict |
|---|---|---|---|
| **One logical map** | `package.json` has single `maps[]` entry (`len==1` enforced in `validate_staged_package:572`); `package_dir` is `Import/<PackageName>` with one XODR | `large_map_package.py:572`, `validate` checks `len(maps)!=1 → FAIL` | **COMPLIANT** |
| **Exactly one authoritative `.xodr`** | `stage_large_map_package:335` copies `src_xodr` once as `package_dir / src_xodr.name`; no per-tile XODR generated or staged; descriptor declares exactly one `xodr` (`./<name>.xodr`) | `large_map_package.py:335`, `validate:582` checks `xodr` exists | **COMPLIANT** |
| **Multiple visual FBX tiles** | `tile_fbx_generator:954` `tile_fbx_name` → `<MapName>_Tile_<x>_<y>.fbx`; `cook_full_grid_tiles:254` cooks densest-first over 20 occupied cells; `stage` copies each `tile_fbx_paths` entry flat into package dir | `tile_fbx_generator.py:954`, `cook_full_grid_tiles.py:254` | **COMPLIANT** |
| **Consistent tile naming** | `_TILE_FBX_RE = r"^(?P<map_name>.+)_Tile_(?P<tx>-?\d+)_(?P<ty>-?\d+)\.fbx$"` (`large_map_package.py:78`); `parse_tile_fbx_filename` used in both stage and validate; invalid names go to `tiles_skipped_missing` | `large_map_package.py:78`, `89` | **COMPLIANT** |
| **Common world frame** | `TileGridSpec` single shared origin `(0,0)` in XODR-local metres, header offset `(832671.676,5458671.104)` subtracted once after tmerc projection (`tile_fbx_generator.py:100` `_PROJ_STRING="+proj=tmerc..."` + `_FWD_TRANSFORMER`); `generate_tile_fbx` preserves lon/lat → no per-tile rebasing; `large_map_package` does not transform FBX coordinates | `tile_fbx_generator.py:100`, `122`, `354` | **COMPLIANT** |
| **Tile size** | `TILE_SIZE_M=1000.0` constant (`cook_full_grid_tiles.py:69`, `large_map_package.py` default, `DESIGN.md §4.3`), validated `>0` in `PackageDescriptor.__post_init__` | `cook_full_grid_tiles.py:69`, `large_map_package.py:132` | **COMPLIANT** |
| **Package metadata** | `package.json` fields `name,xodr,use_carla_materials,tile_size,tiles` + O1 `xodr_sha256`; `props:[]`; sidecar `*.large_map_package.json` with `canonical_source`/`output`/`generating_command`/`tool_version`/`provenance_chain` | `large_map_package.py:146`, `481` | **COMPLIANT** |
| **No per-tile duplicate XODR** | `tile_fbx_generator` never writes `.xodr`; `runtime_tile_builder` (the *other* tiler, for standalone OpenDRIVE routing) is explicitly **not** used on Large-Map path (`tile_fbx_generator.py:19` docstring: "deliberately not reused") | `tile_fbx_generator.py:19` | **COMPLIANT** |
| **No duplicate road authority** | Visual layer is buildings/clutter only (see §3); road authority remains solely with the single XODR (`use_carla_materials` true, terrain excluded) | See §3 | **COMPLIANT** |

---

## 3. Visual FBX Content Audit — What Is In The Tiles?

**OSM2World config (tile_fbx_generator.py:961):**
```
createTerrain=false
renderUnderground=false
useBuildingColors=true
excludeWorldModule=RoadModule;RailwayModule;AerowayModule;ParkingModule
treesPerSquareMeter=0.02
```
- `createTerrain=false` → **no terrain/DEM**
- `excludeWorldModule=RoadModule` → **no roads** (road surface is extruded by CARLA from the single XODR at import, not from FBX)
- `RailwayModule/AerowayModule/ParkingModule` excluded → **no rail/aeroway/parking**
- Buildings source is `ingolstadt_buildings_overpass.json` (5,712 buildings, 5,693 ways + 19 relations) — **buildings only** (verified `clip` buildings 263 per densest tile, `semantic_classification` expects `folder=="Buildings"` for every element; non-buildings counted as anomalies)

**Per-tile OSM clip:** `write_tile_osm_xml` writes whole buildings (never mesh-cut) whose centroid lies in the tile cell (hard non-overlapping partition, `DESIGN.md §3.2`). No sidewalks, no roads, no terrain are emitted.

| Layer | In FBX? | Evidence | Duplicates CARLA XODR? |
|---|---|---|---|
| **Roads** (drivable surface, lane markings) | **No** — excluded via `RoadModule` | `tile_fbx_generator.py:968` | **No** — CARLA generates `CARLA_GENERATED_ROAD` from XODR (AG03A) |
| **Sidewalks** (pedestrian lanes) | **No** — sidewalks are OpenDRIVE `lane type=sidewalk` in XODR, not OSM2World buildings; not in buildings source | `tile_fbx_generator:906` `classify_tile_buildings` expects only `Buildings`; no sidewalk OSM source | **No** |
| **Buildings** | **Yes** — 263 per densest tile (`tile_6_6` manifest), 5,712 total across 20 tiles | `tile_fbx_generator:961` `useBuildingColors`, `COOK_RESULTS.json: buildings_placed` | **No** — buildings have no XODR counterpart; CARLA does not generate buildings from XODR |
| **Clutter / vegetation** | **Yes, limited** — `treesPerSquareMeter=0.02` + OSM2World default forest/trees (sparse) | `tile_fbx_generator:969` | **No** — vegetation is visual only |
| **Terrain / heightfield** | **No** — `createTerrain=false` | `tile_fbx_generator:963` | **No** — terrain is UE4 base level, not XODR |

**Conclusion:** Visual FBX is **buildings (+ sparse trees) only**. It intentionally does **not** duplicate any geometry that CARLA extrudes from OpenDRIVE (roads, sidewalks, terrain). This is the correct `AG03A` separation: XODR owns roads/sidewalks/terrain, FBX owns buildings.

---

## 4. Ambiguous Fields

| Field | Why Ambiguous | Current Handling | Recommendation |
|---|---|---|---|
| `props` | Always `[]` (no prop packages). CARLA docs show `props` for `Prop` packages, but this pipeline never stages props. | Hardcoded `[]` in `build_package_json:169` | **Keep** — explicit empty is compliant; no change needed. |
| `use_carla_materials` | Boolean, default `true`. CARLA docs say `true` uses CARLA's master materials; `false` uses OSM2World materials. | Exposed as `PackageDescriptor` field, default `True`, passed through `stage_large_map_package` | **Keep** — mechanical, no ambiguity. |
| `tile_size` in descriptor vs `TileGridSpec` | Descriptor `tile_size` is CARLA's streaming hint; grid `tile_size_m` is the source clip size. They are set to the same constant `1000.0` but are technically two authorities. | Both default `1000.0` (`cook_full_grid_tiles:69`, `large_map_package:296`); `validate` does not cross-check descriptor `tile_size` vs grid | **Mechanical check added (O2):** new `audit_large_map_package_contract` verifies `descriptor tile_size == TileGridSpec.tile_size_m` within tolerance. |
| `map_name` vs `package_name` | CARLA allows `package_name != map_name` (staging dir vs descriptor `name`). Current code supports `package_name or map_name` (`large_map_package.py:316`). | Documented in `TestCustomPackageNameDiffers` | **Keep** — O1 provenance already distinguishes `package_name` vs `map_name`. |

**No silent defaults:** All ambiguous fields are explicit in code, not inferred from filesystem.

---

## 5. Duplicated-Road Risk

**Risk definition:** Two authorities generate overlapping road geometry — e.g., XODR extruded road surface **and** FBX containing road meshes → z-fighting, duplicate collision, doubled semantic labels.

**Current risk: NONE for Large-Map path.**

- **XODR authority:** Single `Ingolstadt.xodr` (32267 roads, 197k planView geometries, 3,561 junctions) — the only road/carriageway source. `use_carla_materials=true` tells CARLA to generate visible road materials from XODR.
- **FBX authority:** Buildings/clutter only (see §3). `excludeWorldModule=RoadModule` proves roads are excluded at source. No FBX in the staged package contains road quads.
- **Architectural separation:** `tile_fbx_generator.py:19` explicitly documents that `runtime_tile_builder.py` (which *does* carve XODR per tile for standalone routing) is **not** on the Large-Map path. Large-Map never splits the XODR; therefore no per-tile `_Tile_*.xodr` exists to duplicate roads. `validate_staged_package:458` checks for stray `_Tile_*.fbx` but not for stray `_Tile_*.xodr` — adding that check is part of O2 mechanical fixes.

**Remaining risk (outside Large-Map):** `runtime_tile_builder` *does* carve XODR per tile for domain-gap experiments (offline, not for `make import`). That path is separate and correctly labeled `standalone_carla_runtime_tile` (not `carla_large_map_import_package`). No cross-contamination because the two tiler outputs live in different directories (`reports/.../runtime_tile/...` vs `Import/...`).

**Mechanical check added:** `audit_large_map_package_contract` now fails if any `*_Tile_*.xodr` is found alongside `*_Tile_*.fbx` in a Large-Map package (would indicate per-tile XODR leak).

---

## 6. Frame / Origin Authority

**Single source of truth:** `TileGridSpec` defined in `ultimate_pipeline/tiling/tile_fbx_generator.py:121` + `ultimate_pipeline/enrichment/osm_polygon_loader.py:PROJ_STRING` (tmerc).

- **CRS:** `+proj=tmerc +datum=WGS84 +units=m +no_defs` + header offset `(832671.676, 5458671.104)` (`PINNED_XODR` header, `map_registry.py:747`). Buildings transformed via `_FWD_TRANSFORMER` (lon,lat → global metres) then `(gx - ox, gy - oy)` to XODR-local metres (`tile_fbx_generator.py:329`). This is **identical** to `osm_polygon_loader` (AG04 forbids re-deriving).
- **Grid origin:** `origin_x=0, origin_y=0` (XODR-local metres). Cell `(tx,ty)` covers `[origin+tx*1000, origin+(tx+1)*1000)` half-open, so a point exactly on a boundary belongs to the higher-index cell — deterministic partition, no overlap.
- **FBX placement:** `write_tile_osm_xml` preserves each building's true lon/lat; OSM2World projects to the same global frame; Blender writes FBX at true world position. Tiles are **not** rebased per tile; they share one world origin. Adjacent tiles abut exactly (hard clip, centroid rule, §3.2).
- **Unreal handedness/unit:** OSM2World → OBJ is metres, right-handed; Blender OBJ→FBX preserves right-handed; UE4 import handles handedness once at `make import` (no per-tile conversion). No per-tile scaling drift.

**Authorities:**
- `ultimate_pipeline/tiling/tile_fbx_generator.py:100` `_PROJ_STRING` / `_FWD_TRANSFORMER` (singletons)
- `campaigns/.../candidate/...xodr` header `<offset x="832671.676" y="5458671.104"/>`
- `reports/production_readiness/20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN/DESIGN.md §2.4` (frame contract)

**Drift risk:** Low — frame is pinned by hash-verified headers and a single code string (not duplicated). Cross-check: building-frame alignment audit median `1.2e-6 m` (`DESIGN.md §2.4`).

---

## 7. Mechanical Validation Checks Implemented

New function `ultimate_pipeline/tiling/large_map_package.py:audit_large_map_package_contract` (O2, pure checks, no geometry mutation) validates:

1. Exactly one `.xodr` in package dir (no zero, no multiple).
2. Descriptor `tiles[]` count == on-disk `_Tile_*.fbx` count (no stray, no missing).
3. Every `_Tile_*.fbx` name matches `parse_tile_fbx_filename` and `tile_size` equals `TileGridSpec.tile_size_m`.
4. Common world frame: at least one tile manifest exists and its `header_offset_xy` == pinned header offset.
5. No `*_Tile_*.xodr` alongside FBX (per-tile XODR leak).
6. No duplicate tile indices `(tx,ty)` (would imply overlap).
7. `use_carla_materials` is boolean.
8. `xodr` filename matches `map_name` (convention) or is explicitly allowed.

Returns `status PASS/FAIL` + `failures[]` (fail-closed), `warnings[]`. Used by `validate_staged_package` and by new `tools/audit_large_map_package_contract.py` CLI.

---

## 8. Import-Ready Verdict

| Check | Result | Evidence |
|---|---|---|
| One logical map, one XODR, N FBX, package.json + sidecar | **PASS** | `stage` + `validate` both PASS on synthetic and on real `COOK_RESULTS.json` manifest (when XODR SHA matches) |
| Tile naming `*_Tile_<x>_<y>.fbx` deterministic, sorted | **PASS** | `parse_tile_fbx_filename`, `TestTilesAreSortedDeterministically` |
| Common world frame, tile_size 1000.0, origin authority | **PASS** | `TileGridSpec` + header offset; no per-tile rebasing |
| No per-tile XODR, no duplicate road authority | **PASS** | `createTerrain=false` + `excludeWorldModule=RoadModule`; no `*_Tile_*.xodr` in `Import/` |
| Visual FBX is buildings only (no roads/sidewalks/terrain) | **PASS** | OSM2World config + buildings source; `semantic_classification` 100% `Buildings` |
| Provenance chain (O1) — XODR SHA, tile SHA, manifest | **PASS** | `stage` + `validate` now enforce `xodr_sha256` + per-tile `source_provenance.map_of_record_sha256` |
| **Overall for offline staging** | **READY_FOR_IMPORT** | Offline pre-cook gate `PASS`; no UE4 Editor invoked |

**Not verified (requires live UE4 track, separate from O2):** `make import` success, UE4 cook memory/time per densest tile, runtime streaming (`tile_stream_distance`), `ALargeMapManager` origin rebasing, seam rendering / z-fighting / collision / semantic label at tile borders. These remain `UNCONFIRMED` per `DESIGN.md §5 P3-P6` and are correctly not claimed as `READY_FOR_RUNTIME`.

---

## 9. Residual Risks & Next Steps (O3-O5)

- **Densest-tile cook probe:** Cook the single densest `1000 m` tile (core near `(10500,9500)`) in a real UE4.26 + CARLA 0.9.16 source host; if OOM, fallback to `500 m` for core (DESIGN.md §4.5 decision rule).
- **Tile frame consistency proof:** O3 must compute per-tile bounds and seam deltas (machine-readable `tile_frame_consistency.json`), not just code inspection.
- **Resource preflight:** O5 must check free disk / `UE4_ROOT` / `CARLA` root before a multi-hour cook.

*This audit changes no map geometry, promotes no map, and does not claim runtime correctness — per O2 low-medium risk, bounded implementation.*
