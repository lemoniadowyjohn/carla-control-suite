# D-Series Visual and Perception Pipeline Prompts

Date: 2026-08-15

This file records the remaining code-addressable visual/perception pipeline work after the lane-width C5 fix. The final Unreal cook, live capture, training, and real-data evaluation remain non-code/toolchain steps.

## D1 - Vertical Datum Resolution

Status: implemented in this branch as an offline DEM warp tool and a generated uncommitted OBJ artifact.

Task:

- Reconcile the OSM2World visual mesh vertical datum with the elevated XODR road network.
- Keep OSM2World roads excluded; visible road authority remains `CARLA_GENERATED_ROAD`.
- Preserve existing local object heights by adding DEM terrain height to OBJ vertex `y`, not replacing `y`.
- Verify the same DEM is consistent with sampled XODR road elevations.

Acceptance:

- Visual mesh no longer has a flat zero datum for DEM-covered vertices.
- XODR is not mutated.
- Output visual artifact is SHA-anchored and not committed.
- Offline tests and suite stay green.

## D2 - Sensor Calibration Semantics

Status: pending.

Task:

- Resolve the `use_K_undistortion=true` with `ignore_K=true` / `ignore_D=true` contradiction.
- Codify the effective CARLA ideal-pinhole interpretation or escalate if the intended semantics differ.
- Add rig tests for `cTv` vehicle-to-camera direction, `vTl` LiDAR-to-vehicle inversion, image size, and effective intrinsics.

## D3 - Alignment Transform Verifier

Status: pending.

Task:

- Prove the governed mesh-to-XODR-to-Unreal transform is applied exactly once.
- Detect scale 1:100/100:1, X/Y swap, Y/Z inversion, double origin/offset, degree/radian, and stale alignment artifacts.
- Use `submission/results/structural_gap_run11/alignment.json` where applicable; do not derive an ungoverned new transform.

## D4 - Cook Structure Scaffolding

Status: pending.

Task:

- Build the missing UE4.26 / CARLA 0.9.16 cook automation scaffold per `reports/architecture_gate/UNREAL_COOKING_PARAMETERS.md`.
- Include dry-run validation for XODR, FBX/OBJ visual input, transform, semantic partitions, and package layout.
- Do not execute UE/CARLA in offline tests.

## D5 - Fair Capture Protocol

Status: pending.

Task:

- Pin a same-assets, same-rig capture protocol for auto and manual maps.
- Validate protocol config offline so perceptual-gap experiments do not conflate map structure with asset/capture differences.

## Non-Code Gates

- Unreal source/toolchain operator must run the cook.
- Live CARLA capture must be run with the same assets and rig on both maps.
- Real Ingolstadt dataset path and experiment design are external methodology inputs.
