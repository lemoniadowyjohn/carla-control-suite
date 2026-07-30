# AG04 — Coordinate & Vertical Contract

This is the **contract skeleton** the cook campaign must fill (cooking-prompt §8, §36A.2, §36A.3). P4 pins what is *already determined* and flags every stage that is `UNKNOWN → must-resolve`. No new alignment transform is derived here (read-only).

## 1. Transform chain (stage-by-stage)

| Stage | Frame | Units | Handedness / axes | Pinned? |
|---|---|---|---|---|
| 1 | OSM WGS84 lat/lon | degrees | geographic | **bbox pinned**: lat `48.74936–48.77444`, lon `11.42227–11.47882` (Ingolstadt), from `agent_sync.yaml` |
| 2 | Projected CRS | metres | E/N | **UNKNOWN → must-resolve** — no `geoReference`/EPSG/PROJ string tracked in `ultimate_pipeline/`; must be read from the authoritative XODR `<geoReference>` once pinned |
| 3 | OpenDRIVE local metric frame | metres | RH, Z-up | governed by authoritative XODR (unpinned → B2). `<offset>` handling **must-resolve** |
| 4 | FBX source frame | (mesh units) | mesh axis system | **N/A now** (no FBX). Must-resolve when a visual source exists |
| 5 | Unreal frame | **centimetres** | **left-handed, X-forward, Y-right, Z-up** | **pinned by engine** (UE4.26 target). Metre→cm conversion must be applied **exactly once** |
| 6 | CARLA world frame | centimetres | LH | pinned by CARLA |
| 7 | CARLA geolocation | WGS84 | — | round-trip `transform_to_geolocation` / inverse; must be validated at runtime |

## 2. Governing alignment transform (do NOT re-derive)

Per cooking-prompt §36A.2, a governed transform likely already exists in the structural run:
- `submission/results/structural_gap_run11/alignment.json` (tracked) and `auto_aligned_rigid.xodr` — a **rigid + scale** alignment. There is also `tests/unit/test_geo_alignment_rigid_scale_lock.py` locking that convention.
- The cook must **reuse** this governed transform (state source artifact + hash, convention, matrix order, units, whether it applies to XODR/FBX/both, whether the XODR `<offset>` is already incorporated, and prove it is applied **exactly once**). Do **not** derive a new visual alignment independently.

## 3. Vertical / elevation datum — **UNKNOWN → must-resolve**

- Model not yet pinned: flat vs XODR-elevated vs DEM. Supporting code exists (`ultimate_pipeline/{elevation,dem}/`) and `run_11/elevation_stats_auto.json` + `dem_fallback_diagnosis.json`.
- Must record: vertical datum + units, bridge-deck/lower-road separation, tunnel clearance, terrain-to-road offsets, tile-edge elevation continuity, collision-Z vs visual-Z vs waypoint-Z.

## 4. Sensor calibration coupling (from `agent_sync.yaml`) — **CLARIFY before binding**

- `use_K_undistortion=true` **with** `ignore_K=true` and `ignore_D=true` is contradictory on its face. Likely intended semantics: CARLA cameras are **ideal pinhole (no lens distortion)**, so `ignore_K/ignore_D` = "do not apply real-camera intrinsics/distortion" and the effective intrinsics come from resolution+FOV. If so, `use_K_undistortion` is a **legacy/no-op flag** for the sim path. **This must be confirmed and documented** — it directly affects any RGB↔depth↔semantic↔LiDAR registration claim (cooking-prompt §36A.10).
- `ctv_inverted=false`, `vtl_inverted=true` — camera↔vehicle and vehicle↔LiDAR extrinsic storage conventions; must be verified by a rig round-trip.

## 5. Detectors the cook must run (from §8)

Explicitly detect: 1:100 / 100:1 scale error, X/Y swap, Y/Z inversion, RH→LH double reflection, double scale/origin/offset application, yaw-sign inversion, degrees/radians confusion, lat/lon axis-order error, projected-CRS mismatch, height offset, tile-origin duplication. **No manual drag alignment.** Base/tile actors use identity transforms unless the importer requires otherwise (recorded in the contract).
