# CARLA Source Tree Modifications — Disclosure

- **Disclosure date:** 2026-10-07
- **Branch:** `docs/carla-source-tree-mod-disclosure-20261007`
- **Shared tree affected:** `G:\CARLA\carla_source_probe` (checkout of `https://github.com/carla-simulator/carla.git`, detached HEAD `294096eb1`)
- **Scope statement:** This session made **exactly two** modifications to the shared CARLA source tree. Both are **additive and non-destructive**: nothing was deleted, moved, or overwritten in place, and a byte-for-byte backup of every original file was written to `%TEMP%` **before** the edit. No CARLA map, XODR, content/asset, or recipe file was modified. No production cook, no re-cook of the 20 existing Ingolstadt tiles, and no map-of-record pin change was performed.

## Why these changes exist

Task B (road/terrain presence re-verification) required a per-tile actor census that the
stock commandlet did not emit, and Task V4 required an upstream-side exclusion of
pedestrian/groom meshes from the cooking validation path. Both edits live only in the
shared CARLA checkout; neither is committed to any repository tracked by
`carla-control-suite`.

---

## Modification 1 — `VerifyTileWorldsCommandlet.cpp` (instrumentation + rebuild)

| Field | Value |
| --- | --- |
| Date | 2026-10-07 |
| Path | `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Plugins\Carla\Source\Carla\Commandlet\VerifyTileWorldsCommandlet.cpp` |
| Git status in that repo | `??` (untracked — file has **never** been committed upstream) |
| **Original SHA-256** | `991d1020c38b2385307f923ce9171b85052cbf130f2abbd7d530cc18bdd8d5f2` |
| **Modified SHA-256** | `32be2327545a7183ec0c9cad6f3d8113c96849a6772279ade2676809ad1aa992` |
| Original size → modified size | 18,573 B → 27,992 B |
| **Backup (taken before edit)** | `%TEMP%\VerifyTileWorldsCommandlet.cpp.orig` = `C:\Users\admin\AppData\Local\Temp\VerifyTileWorldsCommandlet.cpp.orig` |
| Backup SHA-256 | `991d1020c38b2385307f923ce9171b85052cbf130f2abbd7d530cc18bdd8d5f2` (identical to original) |
| Nature | **Additive** — new census/statistics emission; no existing logic removed |

### What changed

Mesh counting switched to a `TObjectIterator<UObject>` package census (deliberate, see
source comment around lines 160–162) so that every object in each tile package is
classified, and road/terrain presence is reported explicitly instead of being inferred.
`ASplineMeshActor` and `ALandscapeProxy` are filtered/attributed explicitly; instanced
meshes are matched by `ClassName.Contains("InstancedStaticMeshActor")`. The pre-existing
`TActorIterator` paths for the main world were left intact.

### New JSON fields emitted (observed in the produced result file)

- Per tile: `building_actors`, `mesh_actors`, `null_mesh`, `null_static_mesh_actors`,
  `other_static_mesh_actors`, `road_actors`, `roadline_actors`, `sidewalk_actors`,
  `terrain_mesh_actors`, `spline_mesh_actors`, `landscape_components`,
  `landscape_proxies`, `instanced_mesh_actors`, `instanced_mesh_instance_count`,
  `mesh_tag_buckets`, `object_class_histogram`, `package_object_count`,
  `package_actor_count`, `road_terrain_present`, `has_geometry`, `tile_pass`,
  `corrupt_exports`, `null_material_slots`, `loadpackage_success`, `uworld_found`,
  `identity_match`
- Top level: `expected_tiles`, `failures`, `any_road_terrain_present`,
  `mesh_tag_totals`, `object_class_totals`,
  `total_building_actors`, `total_road_actors`, `total_roadline_actors`,
  `total_sidewalk_actors`, `total_terrain_mesh_actors`,
  `total_null_static_mesh_actors`, `total_other_static_mesh_actors`
- Main world: `main_world_found`, `main_world_name`, `main_has_geometry`,
  `main_road_terrain_present`, `main_road_actors`, `main_roadline_actors`,
  `main_sidewalk_actors`, `main_terrain_mesh_actors`, `main_building_actors`,
  `main_mesh_tag_buckets`, `main_object_class_histogram`, `main_landscape_proxies`,
  `main_landscape_components`, `main_spline_mesh_actors`,
  `main_instanced_mesh_actors`, `main_instanced_mesh_instance_count`,
  `main_null_static_mesh_actors`, `main_other_static_mesh_actors`

### Build command (run)

```
Build.bat CarlaUE4Editor G:\CARLA\carla_source_probe\Unreal\CarlaUE4\CarlaUE4.uproject Win64 Development -WaitMutex
```

- Build log: `C:\Users\admin\AppData\Local\Temp\verify_tile_build.log`
- Exit code: `0`, elapsed: `792.64 s`

### Commandlet run (executed)

```
G:\UnrealEngine_4.26_CARLA\Engine\Binaries\Win64\UE4Editor-Cmd.exe ^
  -run=VerifyTileWorlds -PackageName=Ingolstadt -MainMap=Ingolstadt ^
  -OutPath=TILE_EDITOR_LOAD_RESULTS_ROADTERRAIN_20261007.json
```

- Exit code: `0`, elapsed: `709.5 s`
- Result JSON: `carla-control-plane\reports\control_plane\TILE_EDITOR_LOAD_RESULTS_ROADTERRAIN_20261007.json`
  (43,371 B, sha256 `a2cad30ad7ac8631aab8cb9a26013afbd90fb37c2be678be196694a379a394e5`)
- Log: `carla-control-plane\reports\control_plane\tile_load_editor_ROADTERRAIN_20261007.log`
  (834,016 B, sha256 `c13a58c0c4c39a981154a3384242af963ab871ca57e090235ed90e889d6753bd`)
- Receipt: `carla-control-plane\reports\control_plane\ROAD_TERRAIN_CROSSCHECK_20261007.json`
  (29,574 B, sha256 `c7d8e35201112dfaefbf8bf513da28e90942c591d5fd26dd5737373db8089a33`)

### Resulting binary

| Field | Value |
| --- | --- |
| **Rebuilt DLL** | `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Plugins\Carla\Binaries\Win64\UE4Editor-Carla.dll` |
| **SHA-256** | `1188c5fa07fe50199757941ee4e954590578a19862a077e72ca6943def250653` |
| Size / mtime | 10,469,376 B / 2026-10-07 23:18:43 |

> **Note:** this DLL now contains Modification 1's instrumentation. Modification 2 is
> **not** compiled into it (see below).

---

## Modification 2 — `PrepareAssetsForCookingCommandlet.cpp` (source-only filter fix, prompt V4)

| Field | Value |
| --- | --- |
| Date | 2026-10-07 |
| Path | `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Plugins\Carla\Source\Carla\Commandlet\PrepareAssetsForCookingCommandlet.cpp` |
| Git status in that repo | ` M` (tracked and modified) |
| **Original SHA-256** | `096d411638efe8b855bfe3c3235b31a84c46d7592bf7e50313c4a9096b24f3f8` |
| **Modified SHA-256** | `dbd582449609a114a2c3f9c8522cca6e912dcfd510d268dcd3c590d18000da52` |
| Original size → modified size | 31,145 B → 31,719 B (+8 lines, −0) |
| **Backup (taken before edit)** | `%TEMP%\PrepareAssetsForCookingCommandlet.cpp.orig` = `C:\Users\admin\AppData\Local\Temp\PrepareAssetsForCookingCommandlet.cpp.orig` |
| Backup SHA-256 | `096d411638efe8b855bfe3c3235b31a84c46d7592bf7e50313c4a9096b24f3f8` (identical to original) |
| Nature | **Additive** — four exclusion tokens appended to both existing checks; early-return shape unchanged |

### What changed

`ValidateStaticMesh()` (lines 26–52) previously excluded only `light` and `sign`.
Four case-insensitive tokens were appended to **both** the `AssetName` check and the
`MaterialName` check, in the identical `.Contains(TEXT(...), ESearchCase::IgnoreCase)`
+ `||` style:

```
hair, groom, pedestrian, walker
```

This is a **source-code-only** fix for the next production cook cycle.

### Executions explicitly NOT performed

- No build, no UnrealBuildTool invocation, no `UE4Editor-Carla.dll` rebuild
- No cook, no re-cook of the 20 existing Ingolstadt tiles
- No commandlet run, no `UE4Editor-Cmd.exe` invocation
- Evidence: `Get-Process UE4Editor*, UnrealBuildTool, UnrealPak, LiveCodingConsole,
  ShaderCompileWorker` returned no processes at receipt time; DLL SHA-256 unchanged
  from Modification 1 (`1188c5fa…`).

### VCS

No commit and no push were made for this change: the file lives in
`G:\CARLA\carla_source_probe`, which is **not** tracked by this
`carla-control-suite` repository. (Within `carla_source_probe` itself the file is a
tracked ` M` change against detached HEAD `294096eb1`; it was intentionally not
committed there either.)

### Receipt

`carla-control-plane\reports\control_plane\PEDESTRIAN_FILTER_FIX_20261007.json`
(7,383 B, sha256 `f9c172362d4418ac8584d4aae31bedaab642b4d407a148637b2ac9cf3184e587`)
contains the full unified diff, before/after function bodies, execution denials,
backup verification, and VCS statement.

---

## Restoration

Both originals are recoverable byte-for-byte:

```powershell
Copy-Item -LiteralPath "$env:TEMP\VerifyTileWorldsCommandlet.cpp.orig" `
          -Destination "G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Plugins\Carla\Source\Carla\Commandlet\VerifyTileWorldsCommandlet.cpp" -Force
Copy-Item -LiteralPath "$env:TEMP\PrepareAssetsForCookingCommandlet.cpp.orig" `
          -Destination "G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Plugins\Carla\Source\Carla\Commandlet\PrepareAssetsForCookingCommandlet.cpp" -Force
```

`PrepareAssetsForCookingCommandlet.cpp` can alternatively be restored with
`git -C G:\CARLA\carla_source_probe checkout -- <path>` (tracked file).
After restoring either `.cpp`, a rebuild (`Build.bat CarlaUE4Editor … Win64 Development`)
is required for the change to take effect in `UE4Editor-Carla.dll`.

## Explicitly NOT modified by this session

- Any `.xodr`, `.osm`, DEM, or map-of-record pin
- Anything under `G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Content\`
- Anything under `G:\CARLA\carla_source_probe\Import\` (the 20 staged tile FBX files)
- The 20 existing cooked/verified Ingolstadt tiles
- `UE4Editor-Carla.dll` other than the single T6 rebuild recorded above
- Map-of-record registry entries or frozen thesis material

## Evidence index

| Artifact | Path |
| --- | --- |
| Road/terrain cross-check receipt | `carla-control-plane\reports\control_plane\ROAD_TERRAIN_CROSSCHECK_20261007.json` |
| Commandlet result JSON | `carla-control-plane\reports\control_plane\TILE_EDITOR_LOAD_RESULTS_ROADTERRAIN_20261007.json` |
| Commandlet log | `carla-control-plane\reports\control_plane\tile_load_editor_ROADTERRAIN_20261007.log` |
| Baseline result JSON | `carla-control-plane\reports\control_plane\TILE_EDITOR_LOAD_RESULTS_FINAL2.json` |
| Baseline log | `carla-control-plane\reports\control_plane\tile_load_editor_FINAL2.log` |
| Pedestrian filter receipt | `carla-control-plane\reports\control_plane\PEDESTRIAN_FILTER_FIX_20261007.json` |
| Build log | `C:\Users\admin\AppData\Local\Temp\verify_tile_build.log` |
| Backups | `%TEMP%\VerifyTileWorldsCommandlet.cpp.orig`, `%TEMP%\PrepareAssetsForCookingCommandlet.cpp.orig` |
