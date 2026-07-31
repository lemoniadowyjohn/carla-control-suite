# UNREAL_COOKING_PARAMETERS — Parameterization of `05_UNREAL_ENGINE_ASSET_COOKING_PROMPT.md`

**Purpose:** freeze which sections of the cooking prompt **APPLY**, are **DISABLED**, or need **REPLACE** (repo-specific substitution), with the approved exact CARLA/UE values. **This does not execute the cook.** The cook stays blocked until AG07 = `ARCHITECTURE_APPROVED_FOR_CODEX_55` **and** the must-resolve inputs (authoritative XODR, FBX/visible-road decision, source toolchain) are closed.

## Global substitutions (apply everywhere the prompt uses a generic value)

| Prompt token | Approved value |
|---|---|
| Track | **A — UE4.26 / CARLA 0.9.16** (`make`-based). Track B (UE5.5/CMake/World Partition) **DISABLED** |
| `CARLA_ROOT` (runtime) | `E:\CARLA\CARLA_0.9.16` (packaged — runtime only, **cannot cook**) |
| `CARLA` source for cook | **must-resolve** — 0.9.16 source + UE4.26 fork checkout (absent) |
| `CARLA_VERSION` / `PythonAPI` | `0.9.16` (client must match server; fail-closed) |
| `UNREAL_VERSION` | `4.26` |
| `TARGET_PLATFORM` | Cook host **Linux (Docker)**; runtime host is Windows 11 |
| `COOK_CONFIGURATION` | `Shipping` |
| Governance branch/SHA | `integration/governed-map-quality-20260729` @ C55V01a final pushed SHA |
| `run_11` evidence path (prompt §0 is STALE) | **REPLACE** `thesis_results/structural_gap_v1/run_11/` → `submission/results/structural_gap_run11/` |
| Governed structural XODR (prompt §0 is STALE) | **REPLACE** with the C55V01a source-matched candidate `campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr` @ `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d`; structural review still required before mutation/cook |
| Governance checkout `carla_main_governed` (prompt §0) | **REPLACE/RETIRE** — not the current authority; current authority is this branch/SHA |
| OSM2World / Blender / FBX | **FBX visible-road input DISABLED**; visible road authority = `CARLA_GENERATED_ROAD`; OSM2World/Blender artifacts are supplementary environment references only until source-matched to the C55V01a OSM |

## Section-by-section disposition

| § | Title | Disposition | Notes / substitution |
|---|---|---|---|
| 0 | Repository-truth preflight | **REPLACE** | Anchors are stale (branch `verification/map-quality-hardening-20260729` @ `687a69a0`, `carla_main_governed`). Use AG01 authority chain instead. Keep boundaries #1–#6. |
| 1 | Inputs | **REPLACE** | `XODR_INPUT` = C55V01a source-matched candidate above; `FBX_INPUT` = `DISABLED_CARLA_GENERATED_ROAD`; `PYTHON_EXECUTABLE` = project `.venv`. |
| 2 | Version gate | **APPLY (Track A only)** | Pin: CARLA 0.9.16, UE4.26, PythonAPI 0.9.16, `make`. DISABLE the entire Track B block. |
| 3 | Git/worktree safety | **APPLY** | Already partly executed in this gate; forbids `reset --hard`/`clean -fdx`/force-push — consistent with governance. |
| 4 | Architecture discovery | **APPLY** | Component statuses already inventoried in AG02 (reuse, do not duplicate). |
| 5 | Tiled vs monolithic | **APPLY** | Choose `LEGACY_CARLA_LARGE_MAP_TILES` (UE4.26). `UE5_WORLD_PARTITION_MAP` / `HYBRID_*` **DISABLED**. Tile experiment 500/1000/2000 m. |
| 6 | Source/artifact structure | **APPLY** | New campaign under `artifacts/carla_map_cook/<run_id>/` (separate governed namespace — do not touch `run_11`). |
| 7 | Input validation (FBX+XODR) | **APPLY / FBX DISABLED** | XODR validation applies to the C55V01a candidate; FBX visible-road validation is disabled because the selected visible-road authority is CARLA's XODR extrusion. |
| 8 | Coordinate contract | **APPLY** | Fill from AG04; UE target = cm, LH, X-fwd/Y-right/Z-up; reuse governed rigid+scale transform. |
| 9 | Alignment control points | **APPLY** | Numerical evidence decisive; screenshots not sufficient. |
| 10 | Geometry tiling | **APPLY (legacy naming)** | `<MapName>_Tile_<x>_<y>.fbx`; preserve single world origin. |
| 11 | Package description | **APPLY (legacy JSON schema)** | `tile_size` numeric; validate schema against 0.9.16. |
| 12 | Unreal import automation | **APPLY (UE4.26 options)** | Static-mesh import, collision, lightmap UVs. **DISABLE Nanite** (UE5-only). |
| 13 | Semantic classification | **APPLY (UE4 tagger)** | Ignore the UE5/Nanite semantic notes. |
| 14 | Materials/textures | **APPLY** | UE4 material path; no virtual-texture/Lumen assumptions. |
| 15 | Collision | **APPLY** | Per-class; `UCX_/UBX_/UCP_/USP_` naming. |
| 16 | Detached slabs / floating geom | **APPLY** | Zero critical detached road slabs gate. |
| 17 | Level & large-map assembly | **APPLY (CARLA large-map manager)** | **DISABLE World Partition** branch of this section. |
| 18 | Pedestrian navigation | **APPLY if walkers in scope** | Recast after geometry stable; else document as out-of-scope. |
| 19 | Lighting/rendering | **APPLY (UE4 lightmaps)** | **DISABLE Lumen/Nanite** items. Black-in-CARLA = release blocker. |
| 20 | Docker cooking | **APPLY (source-build image, Linux)** | Version-pinned 0.9.16/UE4.26 image; not the runtime-only image; BuildKit secrets; no baked Epic creds. |
| 21 | Full module build | **APPLY (UE4 `make` targets)** | `make setup/LibCarla/PythonAPI/launch/import/package`. **DISABLE** the CMake block. |
| 22 | Example OSM-XODR fixture | **APPLY** | Real cook of a small fixture before full map. |
| 23 | Cook & package | **APPLY (Track A cook path)** | Include XODR + tiles + plugins. |
| 24 | Clean install test | **APPLY** | Prevents stale-same-name false pass. |
| 25 | Runtime load tests | **APPLY** | 3 fresh server cycles; `map.to_opendrive()` hash check vs `map_identity_guard` signature. |
| 26 | Full-scale coverage | **APPLY** | 100% roads/lanes/junctions/tiles/seams. |
| 27 | Waypoint/topology | **APPLY** | Test every previously repaired road/junction. |
| 28 | Drivability | **APPLY** | No excluding failed routes from coverage. |
| 29 | Traffic Manager | **APPLY** | Deterministic seed; density sweep. |
| 30 | Perception | **APPLY** | Sync mode; rig per `agent_sync.yaml` (resolve §36A.10 calibration ambiguity first — AG04). |
| 31 | Runtime coordinate alignment | **APPLY** | Numerical marker overlay vs XODR control points. |
| 32 | Edge cases | **APPLY** | Windows long-path items especially relevant. |
| 33 | Negative controls | **APPLY** | 16 controlled defects incl. HTML-as-.xodr, tile shift, missing texture. |
| 34 | Performance | **APPLY** | Define thresholds from target HW; no universal FPS. |
| 35 | Determinism | **APPLY** | ≥3 runs; matches `agent_sync.determinism` (min_runs 5). |
| 36 | Test profiles | **APPLY** | Skipped mandatory test = release failure. |
| 36A.1 | Road-rendering authority | **APPLY — DECIDED** | Visible-road producer = `CARLA_GENERATED_ROAD`; quarantine OSM2World road/curb/sidewalk from any future environment FBX. |
| 36A.2 | Governing alignment transform | **APPLY** | Reuse `run_11/alignment.json` (do not re-derive). |
| 36A.3 | Elevation/vertical datum | **APPLY** | Resolve AG04 §3. |
| 36A.4 | Traffic lights/signs/landmarks | **APPLY** | XODR signal record insufficient; instantiate CARLA actors. |
| 36A.5 | Unreal automation | **APPLY (UE4 Automation/Gauntlet)** | Discover framework from checked-out branch. |
| 36A.6 | Clean-cache/idempotency | **APPLY** | |
| 36A.7 | Docker branch & host gate | **APPLY — TOOLCHAIN BLOCKER** | 0.9.16 binary ingestion is Linux-only Docker; Windows host must prove WSL2/Linux path. |
| 36A.8 | Secure input handling | **APPLY** | XXE/zip-slip/oversize XODR limits. |
| 36A.9 | Supply chain/license/attribution | **APPLY** | SBOM; OSM ODbL attribution. |
| 36A.10 | Cross-modal sensor consistency | **APPLY** | Depends on AG04 calibration clarification. |
| 36A.11 | Physics-material/drivability | **APPLY** | |
| 36A.12 | One logical map, bounded batches | **APPLY** | One map name, one authoritative XODR. |
| 37 | Hard gates G0–G20 | **APPLY** | G0/G1/G16 (governance/version/evidence-isolation) currently **cannot pass** (see AG07 blockers). |
| 38 | Prohibited shortcuts | **APPLY** | Esp. "don't call `generate_opendrive_world()` cooked-complete" and "don't mix UE4/UE5". |
| 39–41 | Final evidence/report/rule | **APPLY** | Executive verdict must be one of §40's enum; cannot be `PRODUCTION_READY_*` until all §41 conditions hold. |

## Disabled blocks (do not use)

- All **UE5 / `ue5-dev` / CMake-Ninja** build entry points (§2 Track B, §21 CMake block).
- **World Partition** assembly (§17 UE5 branch, §5 `UE5_WORLD_PARTITION_MAP`/`HYBRID_*`).
- **Nanite / Lumen / virtual-texture** requirements (§12, §13, §19).
- The stale §0 anchors (branch/commit/`carla_main_governed`/`thesis_results/...run_11`).

## Repo-specific replacements required before any execution

1. Authoritative **XODR** path + hash (B2): C55V01a candidate `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d`, pending independent structural review.
2. Authoritative **FBX** (or a recorded decision to use `CARLA_GENERATED_ROAD`, dropping the FBX requirement) (B3): `CARLA_GENERATED_ROAD` selected for visible roads; FBX sections disabled for visible-road authority.
3. **CARLA 0.9.16 UE4.26 source** checkout + commit + Docker image digest on a Linux host (B4).
4. **CRS/PROJ** string from the XODR `<geoReference>` (AG04 §1 stage 2).
5. Confirmed **sensor-calibration semantics** (AG04 §4).
