# Tile-Based UE4 Cooking of the Ingolstadt Map-of-Record — Requirements & Phased Design

- **Run ID:** `20260915T140000Z_TILE_BASED_UE4_COOKING_DESIGN`
- **Base commit:** `c8108ecab2f2a75c941b83217650806f15f21bcb` (`integration/session-batch1-20260912`)
- **Design branch:** `docs/tile-based-ue4-cooking-design-v1-20260915`
- **Status:** DESIGN ONLY. No pipeline code changed, no UE4 Editor run (UE4 is not installed on this machine; the cook remains blocked on the separate UE4-build track, per `reports/architecture_gate/AG03_target_architecture.md` step 4 / blocker B4).
- **Map-of-record under study (unmodified):**
  `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`
  sha256 `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`, 148,949,722 bytes (verified this session).
- **Buildings source under study (unmodified):**
  `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json`
  sha256 `f3e8200118845910e136b478a68bd6eb67b985fef6357b98f76ecc6f520e30f5` (verified this session).

Evidence labels used throughout: **[MEASURED]** = computed this session against the pinned artifacts; **[DOCUMENTED]** = from CARLA's official docs or this repo's prior-art reports; **[UNCONFIRMED — needs live UE4 Editor]** = genuinely cannot be known without a cooking-capable UE4.26 + CARLA source build.

---

## 0. Executive summary / key recommendation

The user's framing — "cook the map tile-by-tile as separate maps, with overlap, to make each cook tractable" — is **the right instinct but the wrong mechanism**. CARLA already ships a first-class tiled-cook path, and it is **not** "many separate cooked maps you switch between." It is **one logical map whose *visual* geometry is split into `_Tile_X_Y.fbx` files, sharing one single `.xodr`, streamed at runtime as UE4 sub-levels** (World-Composition-style level streaming driven by ego position). This is CARLA's **Large Maps** feature and it is invoked through the *same* `make import` command, just with a different `package.json` shape. **[DOCUMENTED]**

Concrete recommendations (full reasoning in §1–§5):

1. **Architecture:** Target **one CARLA Large Map** (one XODR + N tiled FBX + a `tile_size` package descriptor), **not** N independent cooked maps. Sub-levels *within* one map, not switchable sub-maps. (§1)
2. **What tiles the FBX, not the XODR:** In a CARLA Large Map the tiling lives entirely on the **FBX/visual** side; the whole 149 MB XODR is imported once, unsplit. So the thing to build is a **per-tile FBX generator**, not a per-tile XODR carve. `runtime_tile_builder.py` solves a *different* problem (standalone-OpenDRIVE-mode routing subsets) and is **not** on the Large-Map cook critical path — though its bbox/curve-aware math is reusable for deciding tile bounds. (§1, §2, §5)
3. **FBX per tile = clip the SOURCE, then render, do not clip the mesh.** The cleanest per-tile FBX is produced by **spatially clipping the buildings/OSM *source* to the tile window and running the existing OSM2World→Blender→FBX path per tile** — reusing the already-tested `clip_osm_window()` pattern (`ultimate_pipeline/tools/phase_j_osm2world_blender.py`). This sidesteps mesh-cutting entirely. (§2)
4. **Overlap/seam:** Use **hard, non-overlapping clip for the RENDER (FBX) layer**, on the exact CARLA tile grid, with a building assigned to **exactly one tile by a deterministic rule (footprint centroid)**. Do **not** carry `runtime_tile_builder.py`'s 100 m routing buffer into the visual layer — an overlap buffer on the render side is precisely what causes double-rendered buildings, z-fighting, and duplicate collision meshes. The routing buffer's job (junction wholeness) is irrelevant to the Large-Map cook because the XODR is never split. (§3)
5. **Tile size:** Recommend **1000 m tiles** as the primary experiment, **500 m as the fallback** for the dense core, on the CARLA-recommended ≤1 km guidance and this map's **measured, highly non-uniform density** (§4). At 1000 m the map is a **14×15 = 210-tile grid**; the densest 1 km² core cells carry ~700–1030 roads and the one measured 1000 m core holds 747 roads (1280 with buffer+closure), while periphery cells are near-empty — so a *uniform* grid will produce very uneven cook cost and the tile-size decision should be validated against a **real cook of the single densest tile**, not against road counts alone. (§4)

The single most load-bearing correction: **"tile-by-tile cooking" for CARLA means tiling the FBX inside one Large Map, not producing separate maps, and the XODR stays whole.** Everything else follows from that.

---

## 1. Multiple cooked sub-maps vs. sub-levels within one map

### 1.1 What CARLA actually documents

**CARLA `make import` (standard, single map)** takes a **paired** `<mapName>.xodr` + `<mapName>.fbx` (identical stem so they are recognized as the same map) and produces one map folder under `Unreal/CarlaUE4/Content`. The standard tutorial (`tuto_M_add_map_source`) documents **no tiling / multi-FBX mode** — its only flags are `--package` and `--no-carla-materials`. **[DOCUMENTED]** So a naive reading of the single-map ingestion docs correctly concludes "no tile mode here" — but that is because tiling is documented separately, under **Large Maps**, and reuses the *same* `make import` entrypoint with a richer descriptor.

**CARLA Large Maps** (`large_map_overview`, `large_map_import`, `content_authoring_large_maps`) is the tiled path: **[DOCUMENTED]**
- The map is **"divided up into tiles … normally set to be about 1 to 2 km in size"**; **"the maximum tile size supported by the CARLA engine is 2 km, we recommend tiles of around 1 km."**
- Tiles are imported from **multiple FBX files** named `"<mapName>_Tile_<x>_<y>.fbx"` (e.g. `Map01_Tile_0_0.fbx`, `Map01_Tile_0_1.fbx`, …), where **"a more positive y coordinate refers to a tile lower on the y-axis."**
- There is **ONE `.xodr` for the whole large map**, not one per tile. The descriptor `package.json` is:
  ```json
  {
    "maps": [
      {
        "name": "Map01",
        "xodr": "./Map01.xodr",
        "use_carla_materials": true,
        "tile_size": 2000,
        "tiles": [
          "./Map01_Tile_0_0.fbx",
          "./Map01_Tile_0_1.fbx",
          "./Map01_Tile_1_0.fbx",
          "./Map01_Tile_1_1.fbx"
        ]
      }
    ],
    "props": []
  }
  ```
  Required map fields: **`name`, `xodr`, `use_carla_materials`, `tile_size`, `tiles`**. `tile_size` default is 2000 (2 km). **[DOCUMENTED]**
- At import each `_Tile_x_y.fbx` becomes **its own UE4 streaming level**; a base map tile `<mapName>` is created as the streaming parent. At runtime tiles are **streamed in/out based on `settings.tile_stream_distance` from the ego/hero vehicle** (default streaming radius examples of 2000). CARLA's `ALargeMapManager` (`CurrentOriginD`, `LocalTileOffset`, `Tile0Offset`, `TileSide`, `GetTileID`) **rebases the world origin to the current tile at runtime** to keep floating-point precision bounded at large coordinates. **[DOCUMENTED]**

### 1.2 The correct mental model

| Option | What it is | Verdict for this map |
|---|---|---|
| **A. Separate cooked maps, switched at runtime** (`world = client.load_world("tile_7_6")`) | N fully independent `.umap`s; only one loaded at a time; a vehicle cannot drive across a seam without a full map reload | **WRONG for a contiguous city.** Breaks continuous driving/routing across seams, duplicates the XODR N times, and defeats the point (each map still cooks its own copy of shared assets). Only makes sense for genuinely disjoint scenes. |
| **B. Sub-levels within ONE map = CARLA Large Map** (World-Composition-style level streaming) | One logical map, one XODR, N tiled FBX → N UE4 streaming levels, ego-position streaming, runtime origin rebasing | **CORRECT.** This is exactly the "tile-by-tile so each cook is tractable" idea, natively supported, and it is what this repo's architecture gate already selected: `LEGACY_CARLA_LARGE_MAP_TILES` (UE4.26), tile experiment 500/1000/2000 m (`AG03_target_architecture.md` decisions #18/#19; `UNREAL_COOKING_PARAMETERS.md` §5/§10/§17). **[DOCUMENTED]** |

**Recommendation: Option B — one CARLA Large Map.** It is the documented feature, it matches the repo's existing pinned architecture decision, and it preserves a single continuous drivable map + single XODR identity (which the repo's `map_identity_guard` determinism signature depends on: `xodr_sha256`, `tile_metadata_sha256`, `tile_count`, `road_count`, `junction_count` — `AG03` decision #26).

### 1.3 What this does to the user's "tile-by-tile cook" idea

The user's tractability goal is *satisfied* by Option B, but the mechanism differs from the mental picture:
- **The heavy per-tile artifact is the FBX, and only the FBX.** Each `_Tile_x_y.fbx` is small and independent; you generate them one at a time, in parallel, and can iterate on one tile without regenerating others. This is the real "make each cook tractable" win.
- **The XODR is imported once, whole.** CARLA extrudes the visible road surface from the whole XODR regardless of FBX tiling; there is no per-tile XODR. So the 149 MB XODR size is *not* reduced by tiling the cook — its cost is paid once at import. (If XODR import itself proves to be the bottleneck, that is a *separate* problem addressed in §4.4, not by FBX tiling.)
- **UE Editor cook cost is amortized per-tile-level, not per-map.** Cooking N streaming levels is more parallelizable and more restartable than one monolithic level; a single bad tile can be re-cooked alone. **[UNCONFIRMED — needs live UE4 Editor]** for the exact per-tile cook time on *this* map.

---

## 2. What each tile's ingestion input must look like (the FBX side)

### 2.1 The requirement, precisely

For a CARLA Large Map, each tile needs an FBX named `<mapName>_Tile_<x>_<y>.fbx` containing the **visual clutter (buildings, and optionally vegetation/retaining walls) whose footprint lies in that tile's spatial cell**, expressed **in the same world frame the whole-map cook uses** (a single shared world origin — CARLA/RoadRunner tiled FBX preserve one global origin; each tile's geometry sits at its true world position, *not* individually re-centered — `UNREAL_COOKING_PARAMETERS.md` §10 "preserve single world origin"). **[DOCUMENTED]**

This is a critical contrast with `runtime_tile_builder.py`:

| Aspect | `runtime_tile_builder.py` (standalone-OpenDRIVE runtime tile) | Large-Map cook FBX tile (this design) |
|---|---|---|
| What is tiled | the **XODR** (roads/junctions) | the **FBX** (buildings/clutter) |
| Coordinate frame | **locally rebased** to tile center; geoReference & offset stripped | **single shared world origin**; tiles keep true positions |
| Overlap | **100 m buffer + junction closure** (routing wholeness) | **no overlap**; hard clip on the cook grid (§3) |
| Consumer | `generate_opendrive_world()` standalone load, no cooking | `make import` → UE4 streaming levels |
| Output | one self-contained `.xodr` + manifest | many `_Tile_x_y.fbx` + one shared `.xodr` + `package.json` |

So `runtime_tile_builder.py` is **not** the FBX-tile producer, and adapting it to be one would be the wrong move: its whole design center (local rebasing + routing buffer + junction closure) is either irrelevant (XODR isn't split) or actively harmful (rebasing/overlap) to the Large-Map cook. Its **reusable parts** are its curve-aware bbox helper (`road_bounds_curve_aware` via `tile_equivalence`) and its clean fail-closed manifest+hash discipline, which the FBX tiler should mirror.

### 2.2 Does anything in the repo produce a spatially-clipped FBX subset today?

**No FBX-mesh clipper exists**, and — importantly — **none is needed**. What exists and is directly reusable is a **source-level spatial clip**:

- `ultimate_pipeline/tools/phase_j_osm2world_blender.py :: clip_osm_window(source, out, window)` **[MEASURED — read in full this session]**: copies OSM `node`/`way`/`relation` elements inside a lat/lon bounding window verbatim (deep-copy), writing a self-contained clipped `.osm`. This is *exactly* the per-tile-window primitive needed, one CRS-level up from the FBX.
- `ultimate_pipeline/enrichment/osm2world_runner.py` (`OSM2WorldRunner`) then renders that clipped `.osm` → OBJ, and `blender_runner.py` converts OBJ → FBX, with `fbx_roundtrip.py` verifying no geometry drift. This whole path was **re-verified at full-map scale this session** (`reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/`): OSM2World 52 s + Blender 6 s + roundtrip PASS on the full 11.1 MB source. **[DOCUMENTED]**

**Therefore the per-tile FBX is produced by clipping the source per tile window, not by cutting a mesh.** "Clip the source, then render per tile" is strictly better than "render whole, then cut the mesh," because:
1. Each tile renders **whole buildings** — no building is ever geometrically severed, so there are no cut-edge artifacts, no half-buildings, no open wall interiors at seams.
2. It reuses tested code (`clip_osm_window` + the verified OSM2World→FBX path) instead of introducing an FBX/mesh boolean-clip dependency.
3. It is embarrassingly parallel and restartable per tile.

### 2.3 The building-source gap that must be closed first (hard dependency)

There is a **known, documented data-routing gap** that blocks *real* building volumes in the FBX regardless of tiling. It is the subject of the concurrent task `feature/osm2world-building-source-fix-v1-20260915` (a live worktree at base this session; no `reports/production_readiness/*_OSM2WORLD_BUILDING_SOURCE_FIX/` evidence directory existed at the time of writing, so its final design is **not assumed here**):

- The pipeline's OSM2World wiring reads `settings.OSM_FILE` → `ingolstadt_authoritative.osm`, which has **`building_way_count: 1`** — it is essentially building-free. **[DOCUMENTED — `FBX_REGEN_CURRENT_PIN` finding #3]**
- The pin's real **5,693 building ways / 19 relations (5,712 objects total)** **[MEASURED this session]** live in `ingolstadt_buildings_overpass.json`, in **Overpass-JSON** format, which OSM2World **cannot consume** (it reads `.osm`/`.osm.xml`/`.pbf` only). The buildings JSON stores geometry as **WGS84 lat/lon** (verified: a sample point is `{lat: 48.7703606, lon: 11.4273401}`), i.e. pre-projection. **[MEASURED this session]**
- **No Overpass-JSON→OSM-XML bridge exists in the repo today.** **[DOCUMENTED]**

**Dependency statement:** the per-tile FBX tiler is only worth building on top of a source that actually contains the buildings. So **"buildings reach OSM2World at all"** (the concurrent building-source-fix) is a **hard predecessor** to a *meaningful* tiled FBX. The tiling design itself is independent of *how* that fix lands (whether it converts JSON→OSM-XML or merges a buildings `.osm`), because the tiler clips whatever building-bearing OSM source is produced. If the concurrent fix produces a single merged building-bearing `.osm`/`.osm.xml`, `clip_osm_window()` clips it per tile unchanged; if it produces OSM-XML directly from the Overpass JSON, same. The one thing the tiler needs from that fix is: **a building-bearing OSM-XML source in a known CRS/frame convention** so the per-tile clip windows can be expressed correctly.

### 2.4 Frame correctness for the clip windows (why this is easy here)

The building source and the XODR are already in the **same coordinate frame after applying the XODR header offset** — the per-building alignment audit measured **median displacement `1.223e-6 m`, p95 `0.000338 m`** across 5,680 shared building IDs (`reports/production_readiness/20260915T120000Z_BUILDING_FRAME_ALIGNMENT/`). **[DOCUMENTED]** The XODR header offset is `(832671.676, 5458671.104)` and geoReference is `+proj=tmerc` (EPSG:32632-family, per AG04). **[MEASURED this session]** So the tile grid can be defined **once in XODR-local metric coordinates** (the same frame `runtime_tile_builder` already uses), and each tile window converted to the lat/lon box that `clip_osm_window` expects via the pinned projection — a deterministic, already-solved transform. No new alignment derivation is needed (AG04 §2 forbids re-deriving it anyway).

---

## 3. Overlap and seams for VISUAL cooking

### 3.1 Why the routing buffer must NOT cross into the render layer

`runtime_tile_builder.py`'s **100 m buffer** exists to keep **junctions structurally whole for routing** in a standalone OpenDRIVE tile (so a car doesn't hit a dangling link at the tile edge). That is a *topology* concern on the XODR. In a Large-Map cook the XODR is never split, so **there is no routing seam to protect** — CARLA extrudes and routes over the whole XODR continuously. The buffer's justification simply does not transfer.

If you nonetheless applied an overlap buffer to the **FBX/visual** layer (e.g. each tile includes buildings within its cell **plus** a 100 m skirt), the failure modes are concrete: **[reasoned; the specific artifacts are UNCONFIRMED — needs live UE4 Editor to see on screen, but the mechanism is standard rendering behavior]**
- **Double-rendered buildings:** any building in an overlap band is emitted in ≥2 tiles and rendered twice.
- **Z-fighting / shadow acne:** two coincident coplanar surfaces from adjacent tiles flicker as the depth buffer ties.
- **Duplicate collision meshes:** two colliders on the same wall → doubled collision events, and (for CARLA semantic/instance sensors) **doubled or flickering semantic labels** — which is corrosive for a *perception* pipeline whose entire purpose is clean labels.
- **Doubled draw cost** exactly in the densest overlap regions, i.e. worst case where you least want it.

### 3.2 Recommended seam strategy (concrete)

**Hard, non-overlapping clip for the render layer, with each building assigned to exactly one tile by a deterministic centroid rule.**

Precisely:
1. Define the CARLA cook grid in XODR-local metres with cell size = `tile_size` (§4), tiles indexed `(x, y)` per CARLA's convention (larger `y` = lower on the y-axis).
2. Assign each building to **the single tile whose cell contains the building's footprint centroid.** (Centroid, not "any-vertex-intersects," guarantees a partition: every building lands in exactly one tile, no building is split, no building is duplicated.) A building straddling a grid line is rendered whole inside its centroid's tile and simply pokes a few metres into the neighbour's cell — which is **fine and correct**: buildings are opaque solids at their true world positions, so a building overhanging a tile boundary is normal and causes **no** z-fighting (there is no second copy to fight with).
3. Emit each tile's FBX at the **shared single world origin** (no per-tile re-centering), so adjacent tiles line up exactly by construction.

This gives **zero double-render, zero duplicate collision, zero label doubling** for buildings, because it is a true spatial partition, not an overlap. It also matches CARLA/RoadRunner's own tiled-FBX assumption (one origin, tiles as a partition).

### 3.3 Why not feathered/blended seams?

Feathering is a terrain/heightfield technique for continuous surfaces (blend two overlapping DEM tiles so the ground doesn't step). This map's tiled layer is **discrete building/clutter meshes**, not a continuous surface, so there is nothing to feather — buildings are either present or not. The **road surface**, which *is* continuous, is owned by CARLA's XODR extrusion (single whole XODR, `CARLA_GENERATED_ROAD` per AG03A), so **road-surface seam continuity is handled by CARLA, not by our tiles at all.** That removes the only place feathering could have mattered.

**Edge case to carry into the cook checklist [UNCONFIRMED — needs live UE4 Editor]:** if vegetation or *terrain/retaining-wall* meshes are ever added to the tiled FBX (OSM2World can emit retaining walls and surface areas — see the `FBX_REGEN` OBJ groups), those *are* semi-continuous and a hard clip can leave a visible 1–2 px gap at a wall that crosses a seam. Mitigation: apply the centroid rule to walls too (whole wall in one tile), or exclude long linear features from tiling and put them in the base tile. This is a minor, later refinement, not a v1 blocker.

---

## 4. Tile size / grid for THIS specific map

### 4.1 Measured density (this session, against the pinned artifacts)

| Metric | Value | Source |
|---|---|---|
| Roads | **32,267** | **[MEASURED]** |
| Junctions | **3,561** | **[MEASURED]** |
| Driving lanes | **34,291** | **[MEASURED]** |
| Total road length | **1,489.15 km** | **[MEASURED]** |
| planView geometry records | **197,397** | **[MEASURED]** |
| Buildings (ways+relations) | **5,712** (5,693 ways + 19 rel) | **[MEASURED]** |
| Extent (XODR-local frame) | **13,276 m (x) × 14,081 m (y)** | **[MEASURED]** |
| bbox area | **186.9 km²** | **[MEASURED]** |
| Road-length density | **8.0 km road / km²** (bbox avg) | **[MEASURED]** |
| Road-count density | **172.6 roads / km²** (bbox avg) | **[MEASURED]** |
| Building density | **30.6 buildings / km²** (bbox avg) | **[MEASURED]** |

The extent is **~13×14 km ≈ 187 km²** — this is unambiguously a "Large Map" (an order of magnitude past the single-tile 2 km limit), so tiling is not optional for the Large-Map path; it is the only supported shape. **[DOCUMENTED + MEASURED]**

### 4.2 Density is strongly non-uniform — the decisive fact

The bbox averages hide a ~5–7× core/periphery skew **[MEASURED]**:
- Densest 1 km² cells: **1,029 roads** (x∈[10000,11000), y∈[9000,10000)), **925**, **857**, **846**, **845** … i.e. the top cells hold **~5–7× the 154 roads/tile bbox average.**
- The one **real data point** from prior art — the 1000 m tile at core center (7195.6, 6796.2) — produced **1,280 roads** with the 100 m buffer + junction closure (`RUNTIME_TILE_SUBSET` evidence). Recomputing the *core-only* count (no buffer, ±500 m box) at that same center gives **747 roads** this session — so the buffer + junction closure roughly *doubles* the raw core count. **[MEASURED + DOCUMENTED]**

### 4.3 Grid options (whole-bbox; averages, not peaks)

| tile_size | grid (x×y) | n_tiles | roads/tile (bbox avg) | note |
|---|---|---|---|---|
| 500 m | 27×29 | **783** | ~41 | many empty periphery tiles; core tiles ~150–250 |
| **1000 m** | **14×15** | **210** | **~154** | **recommended primary**; core tiles ~700–1030 |
| 1500 m | 9×10 | 90 | ~359 | above CARLA's ~1 km recommendation |
| 2000 m | 7×8 | 56 | ~576 | CARLA hard max; core tiles very heavy |

**[MEASURED]**

### 4.4 Recommendation and reasoning

**Primary: `tile_size = 1000` (14×15 = 210-tile grid). Fallback: `500` for the dense core if a 1 km core tile proves too heavy to cook.**

Reasoning:
1. **CARLA's own guidance is "~1 km, max 2 km."** 1000 m sits at the recommended sweet spot; 2000 m is the *maximum*, not a target, and this map's core cells at 2 km would be extremely heavy. **[DOCUMENTED]**
2. **The FBX per tile is what matters for cook tractability, and building density (30.6/km² avg, higher in core) is modest** — a 1 km tile carries on the order of tens of buildings, which the OSM2World→FBX path renders in seconds even for the *whole* map today (52 s full-map). So the FBX side is comfortable at 1 km. **[MEASURED + DOCUMENTED]**
3. **210 tiles is a manageable level count** for UE4 streaming (CARLA ships towns with tens of tiles; hundreds is within the feature's design intent for large maps). 783 tiles at 500 m is a lot of streaming levels and a lot of tiny FBX/UE assets to manage; reserve 500 m for cells that individually fail a cook budget.
4. **The uniform grid is deliberately not "optimal" — and that's acceptable.** A quadtree/adaptive grid (small tiles in the core, large in the periphery) would balance cook cost better, but CARLA's `_Tile_x_y` + single `tile_size` descriptor assumes a **uniform grid** — adaptive tiling is not supported by the documented package format, so a uniform grid is the pragmatic choice. Balance cost instead by **cook-order and parallelism** (cook the ~30–40 non-empty core tiles first/most-carefully), not by non-uniform sizing. **[DOCUMENTED constraint]**

### 4.5 What changes if UE cook cost scales differently than "roads in a domain-gap XODR"

The road counts above are a proxy. The **actual** cook cost is dominated by different things, and the tile-size decision must be *validated*, not assumed: **[UNCONFIRMED — needs live UE4 Editor]**
- If **FBX/building triangle count** dominates cook time → 1 km is fine (buildings are sparse here) and you could even go to 1.5 km on the periphery; road count is a red herring.
- If **XODR-extruded road-mesh triangle count** (lanes × length within the *streamed* region) dominates rendering/collision at runtime → the *streaming distance*, not the tile size, is the lever, and 1 km tiles with a modest `tile_stream_distance` keep the resident set small. Note the XODR is imported whole regardless.
- If **per-level UE overhead** (fixed cost per streaming level) dominates → **fewer, larger tiles win**, pushing toward 1.5–2 km and away from 500 m.
- If **cook *memory*** on the single densest tile is the binding constraint (most likely failure mode for a first cook) → that is exactly why **500 m is the named fallback** and why the plan (§5) cooks the **single densest 1 km tile first as a go/no-go probe**.

**Decision rule for the live track:** cook the densest 1 km tile (core cell near (10500, 9500) or the (7195, 6796) probe center) **in isolation** as the first real cook. If it cooks within the host's memory/time budget, 1 km is confirmed for the whole grid. If it OOMs or is unacceptably slow, drop the core to 500 m (its four sub-cells) and re-probe. Everything else in the grid is lighter than that tile, so one probe bounds the whole map.

---

## 5. Phased plan: what exists, what's a moderate extension, what's genuinely new

Dependencies are explicit. Phases P0→P2 are offline and doable **now**; P3+ require the blocked live UE4 track.

### Ready today (cite real modules)

- **Whole-map density/extent analysis** — done this session (`map_stats.json` in this report dir): 32,267 roads, 187 km² extent, non-uniform density profile. **[MEASURED]**
- **Structural per-tile XODR carve** — `ultimate_pipeline/tiling/runtime_tile_builder.py` (tested; 1000 m tile = 1280 roads, byte-deterministic). Reusable for *routing-subset* experiments and for its bbox math, **but not on the Large-Map cook critical path** (§2.1).
- **Source-level spatial clip** — `phase_j_osm2world_blender.py :: clip_osm_window()` (verbatim node/way/relation clip to a lat/lon window). The per-tile-window primitive. **[MEASURED — read in full]**
- **OSM→OBJ→FBX render path + integrity check** — `osm2world_runner.py`, `blender_runner.py`, `fbx_roundtrip.py`; re-verified at full-map scale this session (52 s + 6 s + roundtrip PASS). **[DOCUMENTED]**
- **Coordinate/frame contract** — AG04 (transform chain, EPSG:32632 tmerc, exactly-once offset) + the building-frame alignment PASS (median 1.2e-6 m). No new alignment to derive. **[DOCUMENTED]**
- **Cook parameterization** — `UNREAL_COOKING_PARAMETERS.md` + AG03/AG05/AG06 already pin Track A (UE4.26/0.9.16, `make import`), Large-Map tiling, tile-size experiment 500/1000/2000 m, `CARLA_GENERATED_ROAD` visible-road authority, single world origin, semantic/collision policy. The design decisions this document makes are **consistent with** that gate, not new architecture. **[DOCUMENTED]**
- **Runtime tile streaming/lookup helpers** — `tile_streamer.py`, `tile_world_runner.py`, `map_registry.py` (bbox lookup, adjacency, logging-only streaming). Adjacent-but-useful for validating streaming behavior later.

### Moderate extension of existing code (offline; buildable now, no UE4)

1. **`clip_osm_window` → per-tile grid clipper.** Generalize the single-window clip into a grid: given `tile_size` + map extent + the pinned projection, emit one clipped building-bearing OSM per `(x,y)` cell, using the **centroid-assignment rule** (§3.2) so it is a partition, not overlapping windows. Reuse the deterministic-write + hash-manifest discipline from `runtime_tile_builder`. **Depends on:** the concurrent **building-source fix** producing a building-bearing OSM-XML source (§2.3) — hard predecessor for *meaningful* output; the clipper is testable against *any* OSM source before then.
2. **Per-tile FBX driver.** Loop the existing OSM2World→Blender→FBX path over the per-tile clipped sources, naming outputs `<mapName>_Tile_<x>_<y>.fbx` per CARLA's convention, emitting at the **shared world origin**. Reuse `fbx_roundtrip.py` per tile. Mostly orchestration around tested components. **Depends on:** extension 1.
3. **`package.json` Large-Map descriptor generator.** Emit the exact documented schema (`name`, `xodr` → the single whole map-of-record XODR, `use_carla_materials`, `tile_size`, `tiles` → the emitted FBX list, `props: []`). Pure serialization; validate against the 0.9.16 schema. **Depends on:** extension 2 (needs the tile list).
4. **Offline pre-cook validation gate.** Assert: every non-empty tile has exactly one FBX; FBX stems match `_Tile_x_y`; XODR sha256 == pinned; no building appears in two tiles (partition check); grid covers the full extent; tile count matches `package.json`. This is the offline analogue of `runtime_tile_builder`'s static validator and can be fully green before any UE4 exists. **Depends on:** extensions 2–3.

### Genuinely new / unproven — requires the live UE4.26 + CARLA-source cook host (blocked on the separate UE4-build track, AG03 step 4 / B4)

All items below are **[UNCONFIRMED — needs live UE4 Editor]**:
5. **First real cook of the single densest 1 km tile** as the go/no-go tile-size probe (§4.5). This is the first thing that turns "1000 m recommended" into "1000 m confirmed."
6. **`make import` of the full tiled package** (one XODR + 210 FBX + package.json) and confirmation that CARLA builds the streaming levels correctly.
7. **Runtime streaming validation:** drive across ≥1 seam, confirm tiles stream in/out by `tile_stream_distance`, confirm world-origin rebasing (`ALargeMapManager`) keeps precision, confirm **no double-render / z-fighting / duplicate collision / doubled semantic labels** at seams (the §3.1 failure list — this is where the hard-clip recommendation is *proven*).
8. **Whole-map coverage cook + perception smoke:** all 210 tiles cook; a perception rig loads and gets clean single-instance labels (no seam doubling); XODR identity hash unchanged vs `map_identity_guard` signature.

**Dependency chain (critical path):**
`building-source fix (concurrent)` → `P1: per-tile grid clipper` → `P2: per-tile FBX + package.json + offline gate` → **[UE4 track unblocks]** → `P3: densest-tile cook probe` → `P4: full tiled import` → `P5: runtime streaming/seam validation` → `P6: whole-map coverage + perception`.
P0–P2 are **fully offline and independent of the UE4 blocker** (they can be built and made green now, gated only on the building-source fix for meaningful content). P3–P6 are all **hard-blocked** on a cooking-capable UE4.26 + CARLA-0.9.16-source host that does not exist on this machine.

---

## 6. Claim boundary

This document is **design and offline measurement only**. It changes no pipeline code, promotes no map-of-record, and starts no CARLA/UE process. The measured numbers are from the pinned artifacts (hashes verified in §0). Every statement about how a *cooked* tiled map behaves at runtime — cook time, memory, seam rendering, streaming, label cleanliness — is explicitly **[UNCONFIRMED — needs live UE4 Editor]** and cannot be closed until the separate UE4-build track completes. `READY_FOR_DESIGN_REVIEW` here means only that the offline evidence and the CARLA-documented feature set support the recommendations; it is not a cook certification.

---

## Appendix A — Reproducing the measurements

The two analysis scripts used this session (read-only, iterparse-based for the 149 MB XODR) computed: whole-map road/junction/lane counts + total length + extent + tile-grid table (`analyze_map.py`), and the density profile + core-tile probe (`analyze_density_profile.py`). Their machine-readable output is `map_stats.json` in this directory. Inputs: the pinned map-of-record and buildings source named in §0, both hash-verified against the values in `RUNTIME_TILE_SUBSET` / `BUILDING_FRAME_ALIGNMENT`.

## Appendix B — Source pointers

- CARLA Large Maps: `large_map_overview`, `large_map_import`, `content_authoring_large_maps`, `large_map_roadrunner` (carla.readthedocs.io/en/latest/). Standard single-map import: `tuto_M_add_map_source`. `ALargeMapManager` (carla.org Doxygen).
- Repo prior art: `reports/production_readiness/20260914T220000Z_RUNTIME_TILE_SUBSET/`; `reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/`; `reports/production_readiness/20260915T120000Z_BUILDING_FRAME_ALIGNMENT/`; `reports/architecture_gate/AG03_target_architecture.md`, `AG04_coordinate_contract.md`, `AG05_unreal_parameters.md`, `UNREAL_COOKING_PARAMETERS.md`.
- Repo modules: `ultimate_pipeline/tiling/runtime_tile_builder.py`, `ultimate_pipeline/tools/phase_j_osm2world_blender.py` (`clip_osm_window`), `ultimate_pipeline/enrichment/{osm2world_runner,blender_runner,fbx_roundtrip}.py`, `ultimate_pipeline/carla_tools/{tile_world_runner,tile_streamer,map_registry}.py`.
