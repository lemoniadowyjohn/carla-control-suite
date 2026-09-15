# Codex PROMPT NN: ingest the pinned Ingolstadt map into a source-built CARLA via `make import`

## Context

This task is the map-cooking step itself, and depends on two things being done first:

1. **PROMPT MM** (UE4+CARLA source build on an external drive) must be complete -- a working
   `UnrealEditor.exe`/`make launch` environment.
2. **PROMPT LL** (regenerate FBX visual-clutter assets from the current pinned map, pushed
   2026-09-14) must be complete -- a fresh, full-coverage buildings/props FBX for the current pin, not
   the stale test-window artifact that existed before.

## Hard prerequisite gate -- check this FIRST

Do not proceed if either prerequisite is missing:

1. Look for PROMPT MM's evidence artifact under
   `reports/production_readiness/*_UE4_CARLA_SOURCE_BUILD/BUILD_STATUS.md` (or `.json`) and confirm its
   final checkpoint is a genuine PASS, not partial/blocked. If missing or not fully passed, STOP and
   report that MM must complete first -- do not attempt a partial ingestion against an unbuilt engine.
2. Look for PROMPT LL's evidence artifact under
   `reports/production_readiness/*_FBX_REGEN_CURRENT_PIN/` and confirm a real FBX file (not the stale
   `reports/post_audit_hardening/20260804T*/artifacts/*_window_osm.fbx`) exists and passed its
   `fbx_roundtrip.py` integrity check. If missing, STOP and report that LL must complete first.
3. Confirm the current pinned map-of-record path/sha256 is still what both prior prompts assumed --
   verify against this campaign's manifest, don't assume it's unchanged.

**If either prerequisite is missing, stop, report exactly what's missing, and do not proceed.**

## Task

1. Prepare `<mapName>.xodr` (the current pinned map) and `<mapName>.fbx` (PROMPT LL's fresh output),
   **with matching base names**, in the CARLA source's `Import/` folder (per CARLA's official ingestion
   docs at carla.readthedocs.io/en/latest/tuto_M_add_map_source/ -- verify the exact folder convention
   against that doc for whatever CARLA version was actually built in PROMPT MM, don't assume it matches
   this prompt's memory of the doc verbatim).
2. Run `make import --package=<a clearly-scoped package name, e.g. ingolstadt_perception_v1>` from the
   CARLA source root built in PROMPT MM.
3. **This is a real city-scale map** (32267 roads, 5682 buildings) -- far larger than CARLA's typical
   small test towns. Flag explicitly if the import process is unusually slow, hangs, or fails in a way
   that looks scale-related (memory, timeout, mesh-count limits) rather than assuming any failure is a
   simple configuration mistake. Do not silently reduce scope (e.g. by dropping buildings or roads) to
   make ingestion succeed without reporting that you did so.
4. On success, confirm real content actually appeared under `Unreal/CarlaUE4/Content/<package_name>/`
   (config files, OpenDRIVE info, static asset info, navigation info per CARLA's docs) -- do not report
   success from `make import`'s exit code alone without checking the actual output exists.
5. Report exactly what the ingestion automated (collision, materials, semantic tags per CARLA's
   documented behavior) versus what still shows as needing manual Editor attention (if anything) --
   this evidence feeds PROMPT OO's investigation, so be precise and complete, not just pass/fail.

## Evidence

Write a dated status artifact to
`reports/production_readiness/<TIMESTAMP>_MAP_INGESTION_MAKE_IMPORT/INGESTION_REPORT.md` (+ `.json`)
recording: exact `make import` command used, full output/errors, confirmed content paths under
`Unreal/CarlaUE4/Content/`, timing, and any scale-related issues encountered.

## Constraints

- Do not attempt a live CARLA load/drive test as "proof of success" -- the GPU-driver TDR livelock
  documented in repo memory (`project_carla_runtime.md`) blocks ANY live CARLA connection on this
  machine regardless of map content, so a failed live-load here is not evidence the ingestion itself
  is broken. Report ingestion success/failure based on `make import`'s own output and the resulting
  Content files, and separately and honestly note that a true load-time verification remains blocked
  on the GPU issue.
- Do not modify the pinned map-of-record or any campaign source files -- only read from them.
- New commits only, never amend. Never force-push. Never skip hooks.
- Full test suite via bare `pytest` must stay green.
- Push your branch and report status; do not merge into `integration/session-batch1-20260912` yourself.
