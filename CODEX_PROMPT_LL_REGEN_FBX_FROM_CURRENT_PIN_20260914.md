# Codex PROMPT LL: regenerate FBX visual-clutter assets from the current pinned map

## Context

An investigation this session (2026-09-14) into "what's needed to cook this
pipeline's map as CARLA/Unreal assets" found that a real, working
OSM2World -> Blender -> FBX export scaffold already exists
(`ultimate_pipeline/enrichment/osm2world_runner.py`,
`ultimate_pipeline/enrichment/blender_runner.py`) with a genuine round-trip
integrity checker (`ultimate_pipeline/enrichment/fbx_roundtrip.py`, which
re-imports the FBX in a clean headless Blender process and diffs geometry
counts against a manifest). This produces visual-clutter meshes (buildings,
vegetation) -- roads themselves stay OpenDRIVE-owned, this does not touch
road geometry.

However, the only FBX artifacts currently on disk
(`reports/post_audit_hardening/20260804T*/artifacts/*_window_osm.fbx`) are
from an old test-window OSM subset (source sha256 `b9e07465...`), not the
current pinned map-of-record
(`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`).
There is no full-coverage FBX export for the current pin. This is a
concrete, low-risk, immediately actionable gap -- unlike full UE4 cooking
(which needs an Unreal Engine + RoadRunner install neither present on this
machine, out of scope for Codex) this task uses infrastructure that already
works today with no missing external dependencies (OSM2World JAR + Blender,
confirm both are actually installed/reachable before starting, do not
assume).

## Task

1. Confirm OSM2World and Blender are actually available on this machine
   (check however `osm2world_runner.py`/`blender_runner.py` themselves probe
   for these -- reuse their own detection logic rather than re-inventing it).
   If either is missing, stop and report that as the blocker; do not
   fabricate a result.
2. Run the existing OSM2World -> Blender -> FBX export path against the
   CURRENT pinned map's building/OSM source data (the same OSM source used
   to build the pinned map -- verify which file that actually is via
   whatever manifest this campaign uses, e.g.
   `campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json`;
   do not assume it is the same OSM window file as the stale 2026-08-04
   artifact).
3. Run `fbx_roundtrip.py`'s integrity check against the freshly-generated
   FBX and report its result (geometry counts, any diffs against the
   manifest, pass/fail).
4. Write the new FBX + supporting evidence (manifest, roundtrip report) to
   a clearly-dated new location (e.g.
   `reports/production_readiness/<TIMESTAMP>_FBX_REGEN_CURRENT_PIN/`),
   explicitly distinct from the stale 2026-08-04 artifacts -- do not
   overwrite or delete those, they may still be referenced elsewhere.
5. If this full-coverage export reveals scale, timing, or memory problems
   the old small test-window export never surfaced (the current pin has
   5682 buildings across the whole Ingolstadt area, likely far more than
   the old test window), report those concretely -- this task is partly
   about finding out whether the existing scaffold actually holds up at
   real map scale, not just re-running it as a formality.

## Constraints

- New commits only, never amend. Never force-push. Never skip hooks.
- Do not attempt to install Unreal Engine, RoadRunner, or any UE cooking
  tooling as part of this task -- that is explicitly out of scope (needs
  the user's own hands-on, heavier authorization) and covered by a separate
  investigation, not this prompt.
- Do not promote anything to `auto_map_of_record`; this task produces a
  visual-asset artifact, not a map-geometry change.
- Full test suite via bare `pytest` (not a manually typed path list) must
  stay green.
- Push your branch and report status; do not merge into
  `integration/session-batch1-20260912` yourself.
