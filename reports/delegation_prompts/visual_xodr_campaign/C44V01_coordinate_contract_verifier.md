# C44V01 — Read-Only Coordinate-Contract & FBX/XODR Alignment Verifier

**Assigned model:** Codex 4.4 Light · **Difficulty:** 4/10 · **Mode:** read-only w.r.t. data (may create verifier code + tests)
**Coordinator:** Claude Opus 4.8 · **Prereq:** DSV01 + DSV02 reports exist. Do NOT select donors independently.

## Allowed to create (only)
coordinate-contract models · read-only CRS parsers · read-only control-point extraction · alignment metrics ·
FBX/OBJ bounds validators · tests · reports.
## Must NOT modify
OSM · XODR · OBJ · FBX · Blender scenes · Unreal projects.

## Coordinate chain (represent explicitly — do NOT assume the projected CRS)
`WGS84/EPSG:4326 → projected map CRS → OpenDRIVE local → OpenDRIVE header <offset> → OSM2World local → Blender scene → FBX → Unreal/CARLA world`.
Parse the projected CRS from: XODR `<geoReference>`, OSM2World config/logs, pyproj strings, settings, manifest metadata.

## Contract schema (emit as JSON; schema_version: 1)
Fields: `source_osm{sha256,bounds_wgs84,crs}`, `projected_map{crs_definition,datum,units,axis_order}`,
`xodr{sha256,geo_reference,header_offset{x,y,z,hdg},local_units}`, `osm2world{version,source_osm_sha256,projection,origin,units,axes}`,
`blender{version,import_units,scene_units,axes,applied_transform}`, `fbx{sha256,export_version,units,axes,global_transform}`,
`unreal{engine_version,import_scale,axes,map_origin}`, `vertical{datum,source,offset,confidence}`.

## Control points
≥6 well-distributed for a small fixture; ≥20 for the full map. Prefer: road intersections, distinct road vertices,
building corners, signal locations, bridge/tunnel endpoints, survey/control points. Each point carries source provenance.

## Alignment model (test transforms in THIS order; scale LOCKED to declared unit conversion)
1. declared exact transform → 2. unit conversion → 3. axis permutation/sign → 4. rigid SE(2) rot+trans → 5. explicit vertical offset.
**Reject** anisotropic scale · shear · reflection not explained by axis conversion · per-tile unrelated transforms.
Do NOT fit free scale unless diagnosing a missing unit conversion.

## Metrics to report
CRS round-trip error · scale ratio · rotation · translation · determinant/reflection state ·
median/p95/max horizontal residual · median/p95/max vertical residual · road-center/building/signal residuals.

## Initial diagnostic thresholds (do NOT auto-broaden)
CRS round-trip ≤ 0.05 m · declared unit scale exact within tol · small-fixture road: median ≤ 0.10 / p95 ≤ 0.25 / max ≤ 0.50 m ·
full-map env: median ≤ 0.25 / p95 ≤ 0.75 / max ≤ 2.00 m · vertical reported SEPARATELY (no PASS when vertical datum unknown).

## Required negative controls (each MUST fail)
10 m translation · 100× scale · X-reflection · Y-reflection · 90° rotation · wrong OSM hash · wrong XODR · wrong FBX · wrong origin · wrong header offset.

## Required outputs
- `reports/visual_structural_reconciliation/C44V01_coordinate_contract.md`
- `reports/visual_structural_reconciliation/C44V01_coordinate_contract.json`
- `reports/visual_structural_reconciliation/C44V01_alignment_results.json`

## Verdicts (return exactly one)
`CRS_CONTRACT_READY` · `FBX_REUSABLE` · `FBX_REQUIRES_DECLARED_TRANSFORM` · `FBX_MUST_BE_REGENERATED` ·
`BLOCKED_MISSING_METADATA` · `FAIL_ALIGNMENT`. Return control to the Claude coordinator (do not proceed to C55V01).
