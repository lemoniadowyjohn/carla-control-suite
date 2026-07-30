# AG03 — Target Architecture Selection + Pinned Decisions

**Target (exactly one): `E_COOKED_LOADABLE_CUSTOM_MAP`** — reached via **Track A (CARLA 0.9.16 / Unreal Engine 4.26)**.
**Status of target: SELECTED-BUT-NOT-YET-ACTIONABLE** — the two primary inputs the cook requires (an authoritative FBX visual mesh and a pinned authoritative XODR describing the *same* map) do not exist in a pinned form in this worktree (see blockers B2/B3 in AG07).

## 1. Track selection (cooking-prompt §2 version gate)

- Anchor: `E:\CARLA\CARLA_0.9.16` — a **packaged** build (`CarlaUE4.exe`, `Engine`, `HDMaps`, `Import`). CARLA 0.9.16 ⇒ the **UE4.26** line ⇒ **Track A** (`make import/launch/package`).
- **Track B (UE5.5 / `ue5-dev` / CMake) is DISABLED.** No UE5 tree, no CMake CARLA targets, no World Partition support in this branch. Mixing Track A and Track B is explicitly prohibited (cooking-prompt §38) → doing so would force `G_MULTIPLE_CONFLICTING_PATHS`.
- ⚠ **Toolchain gap:** the packaged install **cannot cook**. Cooking requires a **CARLA source checkout at 0.9.16 with the UE4.26 fork** — which is **absent** here — and, per cooking-prompt §36A.7, the 0.9.16 binary-ingestion path is **Linux-only Docker**; the host is **Windows 11**. This is the toolchain blocker (AG05, AG07-B4).

## 2. Mandatory architecture decisions (every field pinned; `UNKNOWN → must-resolve` flagged)

| # | Decision | Pinned value | Confidence |
|---|---|---|---|
| 1 | CARLA repository | `carla-simulator/carla` (official) | HIGH |
| 2 | CARLA branch/tag | `0.9.16` release (UE4.26 line) | HIGH (from install metadata) |
| 3 | CARLA commit | **UNKNOWN → must-resolve** (packaged build; source commit not pinned) | — |
| 4 | Unreal version | **UE4.26** (CARLA `carla-simulator/UnrealEngine` 4.26 fork) | HIGH |
| 5 | Unreal commit | **UNKNOWN → must-resolve** | — |
| 6 | PythonAPI version | `0.9.16` (must match server; fail-closed on mismatch) | HIGH |
| 7 | Build system | `make` (Track A). **NOT** CMake/Ninja (that is Track B/UE5) | HIGH |
| 8 | Native vs Docker | **Docker (Linux)** required for cook; native Windows cook is unsupported for 0.9.16 | MEDIUM → must-resolve host |
| 9 | Host support | Runtime: Windows OK. **Cook: needs Linux/WSL2+Docker or native Linux** — not proven on this host | must-resolve |
| 10 | Visible-road authority | **CURRENT:** CARLA runtime extrusion from XODR (`load_world`). **TARGET:** must select exactly one of `XODR_DERIVED_MESH` / `CARLA_GENERATED_ROAD` / `ROADRUNNER_MESH` (cooking-prompt §36A.1) — **DECISION REQUIRED at cook (P6), recommend `CARLA_GENERATED_ROAD` unless a proven FBX road mesh exists** | must-decide |
| 11 | OSM2World role | **Supplementary, referenced-but-source-absent, non-authoritative, NOT integrated.** If ever used, environmental geometry only; road/curb/sidewalk objects must be quarantined by semantic filter | HIGH |
| 12 | Blender role | **NONE** (absent) | HIGH |
| 13 | Authoritative XODR | **UNKNOWN → must-resolve.** `settings.INPUT_XODR` = computed path `{CITY}_osm_auto.xodr` to a non-tracked runtime file; `MANUAL_MAP_XODR` default `""`; only tracked XODR is a results artifact | **BLOCKER (B2)** |
| 14 | Authoritative FBX/visual input | **ABSENT → must-resolve** (0 tracked FBX) | **BLOCKER (B3)** |
| 15 | Coordinate transform | WGS84 → projected CRS → OpenDRIVE metric → FBX → UE cm (LH, X-fwd, Y-right, Z-up) → CARLA world. bbox pinned (Ingolstadt). **CRS/PROJ string UNKNOWN → must-resolve** (no `geoReference`/EPSG tracked) | must-resolve |
| 16 | Vertical transform | **UNKNOWN → must-resolve** (flat vs XODR-elevated vs DEM). `ultimate_pipeline/{elevation,dem}/` exist; `run_11` has `elevation_stats_auto.json` | must-resolve |
| 17 | Manual/reference map role | Grid0821/Grid0828 = **evaluation reference only**, not production input. Provenance drift (mislabeled `grid0828` file carrying Grid0821 content) is a **P5 registry** task, not P4 | HIGH |
| 18 | Monolithic vs tiled | **TARGET:** `LEGACY_CARLA_LARGE_MAP_TILES` (UE4.26). **NOT** UE5 World Partition | MEDIUM (default full-scale) |
| 19 | Tile-size experiment | Evaluate 500 m / 1000 m / 2000 m; pick smallest tile count within memory/streaming limits (cook-time) | deferred |
| 20 | Semantic partition strategy | CARLA UE4 tagger (asset naming + content folders + tagger code) | deferred |
| 21 | Traffic-light/sign strategy | XODR signals → CARLA traffic-control **actors** (branch-specific). Currently XODR signal *records* only, no instantiated actors | must-resolve |
| 22 | Collision strategy | Per-semantic-class (continuous driveable roads; simplified buildings; explicit curb/bridge policy) | deferred |
| 23 | Navigation strategy | Recast pedestrian nav after geometry/collision stable | deferred |
| 24 | Runtime session owner | `ultimate_pipeline/carla_tools/session.py` (+ `map_identity_guard.py`, `sensor_registry.py`) — **current authoritative owner** | HIGH |
| 25 | Sensor calibration contract | `agent_sync.yaml`: `use_K_undistortion=T`, `ignore_K=T`, `ignore_D=T`, `ctv_inverted=F`, `vtl_inverted=T`. ⚠ **Clarify** `use_K_undistortion` vs `ignore_K/ignore_D` contradiction | pinned + clarify |
| 26 | Dataset identity contract | determinism signature = `xodr_sha256`, `tile_metadata_sha256`, `tile_count`, `road_count`, `junction_count`; enforced by `map_identity_guard` | HIGH |

## 3. Path A → E (what must happen, in order)

1. Close base governance (P2 hook test) — *precondition, not architecture*.
2. Pin an **authoritative XODR** (real, tracked, hashed, provenance-verified) — resolves B2.
3. Provide/produce an **authoritative FBX** describing the *same* map (or select `CARLA_GENERATED_ROAD` and drop the FBX requirement) — resolves B3/decision #10.
4. Stand up a **CARLA 0.9.16 UE4.26 source build** on a supported (Linux/Docker) host — resolves B4/toolchain.
5. Only then execute the parameterized cooking prompt (AG05) under a separate governed run namespace.

Steps 2–4 are **base/architecture-input corrections**, which is why the gate verdict is `REQUIRES_BASE_CORRECTION` (AG07), not `ARCHITECTURE_APPROVED`.
