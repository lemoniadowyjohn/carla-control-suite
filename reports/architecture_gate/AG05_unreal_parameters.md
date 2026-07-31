# AG05 — Unreal Cooking Prompt Parameterization (summary)

Full section-by-section disposition: **`reports/architecture_gate/UNREAL_COOKING_PARAMETERS.md`**.

## Decision summary

- **Track A only** (CARLA 0.9.16 / UE4.26 / `make`). **Track B (UE5.5/CMake/World Partition/Nanite/Lumen) fully DISABLED.** Mixing them would force `G_MULTIPLE_CONFLICTING_PATHS` (prohibited, §38).
- **Cook host:** Linux + Docker (source-build image, version-pinned). The packaged `E:\CARLA\CARLA_0.9.16` is **runtime-only and cannot cook**. Windows host must prove a WSL2/Linux path (§36A.7) → **toolchain blocker**.
- **Tiling:** `LEGACY_CARLA_LARGE_MAP_TILES` with `<MapName>_Tile_<x>_<y>.fbx` naming; tile-size experiment 500/1000/2000 m.
- **Stale prompt §0 anchors REPLACED:** `run_11` path → `submission/results/structural_gap_run11/`; governance branch/SHA → `integration/governed-map-quality-20260729 @ 5eddcc54`; `carla_main_governed` retired.

## UNREAL PROMPT READY = **NO (parameterized, not authorized)**

The parameterization is complete and binding, but three inputs must close first:
1. Authoritative **XODR** (pinned, tracked, hashed) — B2. **[07-31 #2: CLOSED @ 64139d3b]**
2. Authoritative **FBX** *or* a recorded `CARLA_GENERATED_ROAD` decision — B3. **[07-31 #2: decision recorded; B3 CLOSED]**
3. **CARLA 0.9.16 / UE4.26 source** build on a supported Linux/Docker host — B4.

Plus resolve: CRS/PROJ from XODR `<geoReference>`, vertical datum, and the sensor-calibration contradiction (AG04).

**The cooking prompt must NOT be executed by P4 or P5.** It runs only after AG07 approval *and* B2–B4 closure, under a separate governed run namespace that leaves `run_11`/thesis evidence untouched.
