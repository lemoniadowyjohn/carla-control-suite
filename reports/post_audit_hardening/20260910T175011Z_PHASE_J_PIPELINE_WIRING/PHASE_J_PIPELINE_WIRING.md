# Phase J Pipeline Wiring

Date: 2026-09-10

## Scope

`MainPipeline` now runs OSM2World once, after the final structural XODR is
frozen and before tiling. The call is opt-in through `UP_ENABLE_OSM2WORLD`,
`ENABLE_OSM2WORLD`, or `Settings.ENABLE_OSM2WORLD`. Stage 04 records an
explicit deferred status and no longer invokes the renderer before geometry and
lanes are stable.

OpenDRIVE remains the road authority. Generated visual assets are supplemental
only and cannot modify the final XODR. The enabled stage writes
`osm2world_pipeline_stage.json`, artifact provenance sidecars, and J1 results.
A renderer failure, failed J1 validation, or unvalidated-only output set raises
after writing that receipt. Missing external tooling is `BLOCKED_EXTERNAL`.

## Full-Scale Result

The real governed Ingolstadt OSM source was processed against the pinned map
identity `2ca342d8...fDE4798`. Java 17.0.17, OSM2World
`OSM2World.jar` (`f20b00e1...cb61fac`), and Blender 4.3.0 were available.

OSM2World returned `ok` in 4.052 seconds and produced an OBJ with 945 vertices,
876 faces, and 64 object groups. The one run used a stable stage-local output
name, but it did not execute J2's repeatability protocol or standalone
map/campaign naming-contract validation, so J2 is `INCOMPLETE`. J1 rejected that OBJ because four names appear
multiple times: `SurfaceArea Audi - Parkplatz` (6), `SurfaceArea Bahnhof
Ingolstadt Audi` (2), `SurfaceArea Rathausplatz` (2), and `SurfaceArea Zentraler
Omnibusbahnhof (ZOB)` (20). Provenance linkage, artifact hash, finite
coordinates, face degeneracy, material linkage, and MTL validation passed.

The pipeline receipt therefore reports `runner_status=ok` and `status=FAIL`.
This is intentional: renderer completion is not visual/collision certification.
OSM2World also wrote duplicate-point polygon errors to stderr despite its zero
exit code. Blender/FBX/collision stages J3-J8 were not run after J1 failed.

## Verification

Focused Phase J coverage: `56 passed, 6 warnings`.

The complete offline suite was executed with CARLA disabled and streaming wait
set to zero to prevent the fake-client unit test from probing the CARLA streaming
port. It completed with `5663 passed, 79 failed, 85 skipped, 2 errors`. The
failures require sparse-worktree-excluded governed maps, research contracts,
RoadRunner profiles, calibration configuration, and historical evidence. They
are not hidden or reclassified as passing; the full-suite result is `FAIL`.

No CARLA process was started, no CARLA RPC was called, the map-of-record was
not changed, and frozen evidence was not modified. Raw external artifacts and
the complete receipts remain in the detached experiment directory recorded in
the JSON evidence.

## Verdict

Pipeline wiring: `PASS`.

Full-scale Phase J certification: `FAIL` at J1. Production activation remains
out of scope and is not enabled by this change.
