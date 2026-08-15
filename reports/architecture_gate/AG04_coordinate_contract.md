# AG04 — Coordinate & Vertical Contract

This is the **contract skeleton** the cook campaign must fill (cooking-prompt §8, §36A.2, §36A.3). P4 pins what is *already determined* and flags every stage that is `UNKNOWN → must-resolve`. No new alignment transform is derived here (read-only).

## 1. Transform chain (stage-by-stage)

| Stage | Frame | Units | Handedness / axes | Pinned? |
|---|---|---|---|---|
| 1 | OSM WGS84 lat/lon | degrees | geographic | **bbox pinned**: lat `48.74936–48.77444`, lon `11.42227–11.47882` (Ingolstadt), from `agent_sync.yaml` |
| 2 | Projected CRS | metres | E/N | **UNKNOWN → must-resolve** — no `geoReference`/EPSG/PROJ string tracked in `ultimate_pipeline/`; must be read from the authoritative XODR `<geoReference>` once pinned **[07-31 #2: RESOLVED — EPSG:32632 (tmerc 9E) read from pinned XODR ff2a05e7]** |
| 3 | OpenDRIVE local metric frame | metres | RH, Z-up | governed by authoritative XODR (unpinned → B2). `<offset>` handling **must-resolve** **[07-31 #2: XODR pinned ff2a05e7; B2 CLOSED]** |
| 4 | FBX source frame | (mesh units) | mesh axis system | **N/A now** (no FBX). Must-resolve when a visual source exists |
| 5 | Unreal frame | **centimetres** | **left-handed, X-forward, Y-right, Z-up** | **pinned by engine** (UE4.26 target). Metre→cm conversion must be applied **exactly once** |
| 6 | CARLA world frame | centimetres | LH | pinned by CARLA |
| 7 | CARLA geolocation | WGS84 | — | round-trip `transform_to_geolocation` / inverse; must be validated at runtime |

## 2. Governing alignment transform (do NOT re-derive)

Per cooking-prompt §36A.2, a governed transform likely already exists in the structural run:
- `submission/results/structural_gap_run11/alignment.json` (tracked) and `auto_aligned_rigid.xodr` — a **rigid + scale** alignment. There is also `tests/unit/test_geo_alignment_rigid_scale_lock.py` locking that convention.
- The cook must **reuse** this governed transform (state source artifact + hash, convention, matrix order, units, whether it applies to XODR/FBX/both, whether the XODR `<offset>` is already incorporated, and prove it is applied **exactly once**). Do **not** derive a new visual alignment independently.

## 3. Vertical / elevation datum — **D1 resolved; D1b review pending**

- D1 pins the visual mesh vertical datum to the same DEM source used by the elevated XODR road network. See `reports/post_audit_hardening/D1_VISUAL_VERTICAL_DATUM.md` and `D1_VISUAL_VERTICAL_DATUM_RUN.json`.
- D1b decomposes road-to-DEM residuals by F3 structure class. At-grade p95 is within threshold, but the at-grade max tail breaches the review threshold, so bridge/deck separation does **not** fully explain the tail. See `reports/post_audit_hardening/D1B_ELEVATION_RESIDUAL_DECOMPOSITION.md`.
- Still required before cook: bridge-deck/lower-road separation review for the residual tail, tunnel clearance, tile-edge elevation continuity, collision-Z vs visual-Z vs waypoint-Z, and D3 exact-once transform verification.

## 4. Sensor calibration coupling (from `agent_sync.yaml`) — **D2 resolved**

- CARLA cameras are treated as ideal pinhole cameras with no simulated lens distortion. `ignore_K=true` and `ignore_D=true` mean the raw real-camera `K` and `D` matrices are not applied in the simulator.
- `use_K_undistortion=true` is retained as a legacy contract flag meaning: derive the effective CARLA camera intrinsics/FOV from rectified `K_undistortion` plus `image_size`, not from raw `K` or `D`.
- `ctv_inverted=false` is locked as `cTv` vehicle-to-camera used directly, not inverted.
- `vtl_inverted=true` is locked as `vTl` LiDAR-to-vehicle inverted to produce the CARLA vehicle-to-LiDAR attachment transform.
- The canonical calibration file is now `ultimate_pipeline/sensors/calib_data.json`; D2 round-trip evidence is tracked in `reports/post_audit_hardening/D2_SENSOR_CALIBRATION_SEMANTICS.md` and `.json`.

## 5. Detectors the cook must run (from §8)

Explicitly detect: 1:100 / 100:1 scale error, X/Y swap, Y/Z inversion, RH→LH double reflection, double scale/origin/offset application, yaw-sign inversion, degrees/radians confusion, lat/lon axis-order error, projected-CRS mismatch, height offset, tile-origin duplication. **No manual drag alignment.** Base/tile actors use identity transforms unless the importer requires otherwise (recorded in the contract).
