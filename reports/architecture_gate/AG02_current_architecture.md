# AG02 — Current Architecture Classification

**Classification (exactly one): `A_RUNTIME_XODR_ONLY`**

## 1. Decisive evidence (verified in the working tree @ `5eddcc54`)

| Probe | Result | Implication |
|---|---|---|
| `Unreal/ carla/ Import/ Content/ CarlaUE4/` in worktree | **ABSENT** (all 5) | No Unreal source/cooked tree → not D/E |
| Tracked `*.fbx` / `*.FBX` | **0 files** | No authoritative visual/mesh input → cannot be a cooked-mesh path |
| Tracked `*.xodr` | **1 file** — `submission/results/structural_gap_run11/auto_aligned_rigid.xodr` (a *results* artifact, not a pinned input map) | No authoritative input XODR is committed |
| Runtime session (`carla_tools/session.py`) | `self._client.load_world(map_name)` + `reload_world()`; guarded by `map_identity_guard.py` | Runtime loads a **named** CARLA world; visible roads come from CARLA's XODR path, not custom art |
| `ultimate_pipeline/osm/`, `tiling/`, `perception/` | **0 tracked `.py`** — only orphaned `__pycache__` (`osm_to_xodr.pyc`, `osm_downloader.pyc`, `osm_to_xodr_wrapper.pyc`) | Named "subsystems" are **source-absent** in the tracked tree → not a reproducible producer |
| OSM2World references | only `config/settings.py`, `main_pipeline.py`, `pipeline_stages/stage_04_enrichment.py` | Referenced, **not integrated** (its `osm/` producer source is gone) |
| Blender references (tracked, pipeline) | **0** | No Blender stage exists |
| RoadRunner-class maps (Grid0821/Grid0828) | live in **sibling worktrees / reference role**, not integrated here | Not an authoritative production map in this branch → not F |

## 2. Why `A_RUNTIME_XODR_ONLY` and not the alternatives

- **not B_RUNTIME_XODR_WITH_PROXY_ENRICHMENT** — `stage_04_enrichment.py` *references* OSM2World, but the `osm/` producer source is absent (only `.pyc`), so no enrichment path is reproducible or wired into a runtime world. The B path is **latent and non-functional**, not active.
- **not C_SUPPLEMENTARY_OSM2WORLD_BLENDER_NOT_INTEGRATED** — there is **no Blender** at all, and no OSM2World mesh output present; C overstates the presence of a supplementary geometry pipeline.
- **not D_PARTIAL_UNREAL_CUSTOM_MAP / E_COOKED_LOADABLE_CUSTOM_MAP** — no `Unreal/` tree, no FBX, no cooked package, no `Content/`.
- **not F_ROADRUNNER_AUTHORITATIVE_MAP** — Grid0821/0828 are evaluation reference maps in other worktrees; none is the authoritative production map of this branch.
- **not G_MULTIPLE_CONFLICTING_PATHS** — there is exactly **one** live path (runtime XODR). The conflicts that exist are about *which XODR is authoritative* (unpinned; see AG03/AG04) and *provenance drift* in reference maps — **not** competing build/cook architectures. G is reserved for mixed UE4/UE5/tiling toolchains, which are all absent.

## 3. What "runtime-XODR-only" means for claims

The live system's visible roads, waypoints, and topology are whatever CARLA derives from an OpenDRIVE world at runtime (`load_world`). There is **no custom cooked mesh, no FBX art, no baked semantics/collision beyond CARLA's XODR extrusion**. Any perception evidence produced to date is bounded by that fact and **cannot be retroactively described as a "cooked custom perception map."**

## 4. Component inventory (cooking-prompt §4 taxonomy)

| Component | Status |
|---|---|
| Runtime session owner (`carla_tools/session.py`) | OPERATIONAL_UNVERIFIED |
| Map identity guard (`carla_tools/map_identity_guard.py`, tests present) | OPERATIONAL_UNVERIFIED |
| Sensor registry (`carla_tools/sensor_registry.py`) | PARTIAL |
| OpenDRIVE geometry authority (`opendrive_geometry/` primitives, evaluator, cross-compare) | PARTIAL/VERIFIED (math) — see project geometry-lineage caveats |
| Artifact transaction layer (`ultimate_pipeline/artifacts/{store,transaction,promotion,recovery,semantic_diff,model,errors}.py`) | PARTIAL — `hashing.py`+`locking.py` ABSENT (P5 scope) |
| OSM→XODR producer (`osm/`) | ABSENT (source-absent; only `.pyc`) |
| Tiling producer (`tiling/`) | ABSENT (source-absent) |
| Perception producer (`perception/`) | ABSENT (source-absent) |
| FBX import / Blender / Unreal import / cook / package | ABSENT |
| Coordinate-transform module (CRS/PROJ) | ABSENT — no `geoReference`/EPSG/PROJ tracked in pipeline |
