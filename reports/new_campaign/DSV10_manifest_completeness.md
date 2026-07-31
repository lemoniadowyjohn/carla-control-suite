# DSV10 — Campaign-Manifest Completeness Audit

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY · **Task ID:** DSV09-LEDGER batch
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `7506128da4e3bd56e0bb8a010cb0abd03f7ab7d0`
**Verdict:** `MANIFEST_FIELDS_MISSING` — 5 field groups unbound (3 N/A-by-policy), all critical identifiers present

Audited: `campaigns/ingolstadt_cooked_perception_v1/manifest.json` (741 L), `candidate/manifest.json` (649 L), `source/manifest.json` (39 L), `visual/manifest.json` (46 L), `candidate/osm_to_xodr_conversion_status.json`.

## Field matrix

| # | Required field | Status | Evidence |
|---|---|---|---|
| 1 | Git SHA | ✅ present | `approved_base_sha a7919117`, `execution_base_sha c264e0c8`, `generation_head_sha c264e0c8`, `upstream_sha_at_generation`, `branch` (L4-8) |
| 2 | OSM SHA | ✅ present | `source_osm.sha256 b9e07465…` + `byte_size 11,154,738` (L16-17); same in `source/manifest.json` |
| 3 | OSM bounds | ✅ present | `bounds_wgs84` (full bbox) + `study_bounds_wgs84` (region Ingolstadt) + `covers_study_bounds: true` (L23-36); OSM version, Overpass generator, source_date, license, node/way/relation counts (L19-45) |
| 4 | Converter profile | ⚠️ PARTIAL | `osm_to_xodr_conversion_status.json` pins `donor_root` (codex-full-pipeline-rerun-20260427), per-run `duration_s`, `status: CONVERSION_SUCCEEDED`; but NO converter tool name/version field in any manifest |
| 5 | CARLA / Osm2Odr version | ❌ missing | no version strings anywhere (donor code variant `osm_to_xodr_wrapper.py 2678373C3AC9…` implied by DSV02, not bound in manifest) |
| 6 | CRS-contract hash | ⚠️ PARTIAL | `geo_reference` full PROJ string pinned on candidate (L54) + `geo_reference_matches_epsg32632: true` (L55); C44V01 report exists (`reports/visual_structural_reconciliation/C44V01_coordinate_contract.{md,json}`) but no contract-hash field in the manifest |
| 7 | DEM hash / flat-zero | ✅ present (explicit flat-zero) | `vertical` block (L709-713): `datum LOCAL_FLAT_ZERO_NO_DEM`, `offset_m 0.0`, `source` describes no-DEM flat profile; `elevation_metrics` (L243-252): `elevation_record_count 32710`, `nonzero 0`, `all_bcd_zero true`, `nonfinite 0`, `profile_classification LOCAL_FLAT_ZERO_NO_DEM` |
| 8 | OSM2World version | ❌ missing (N/A-by-policy) | only artifact paths in `rejected_visible_road_fbx_artifacts` (L676-702); no version; policy is CARLA_GENERATED_ROAD so OSM2World is not in the selected chain |
| 9 | Blender version | ❌ missing (N/A-by-policy) | same artifacts list (classification `BLENDER_EXPORT_PROVEN` but no version); not in selected chain |
| 10 | Visual config | ✅ present | `visual` block (L668-708): `visible_road_authority CARLA_GENERATED_ROAD`, `visual_sha256 "CARLA_GENERATED_ROAD"`, `fbx_role FBX_ENVIRONMENT_ONLY`, `selected_policy`, `source_matched_to_osm_sha256 b9e07465…`, decision_reason; `visual/manifest.json` verdict `CARLA_GENERATED_ROAD_RATIFIED` |
| 11 | Random seeds | ❌ missing | no seed field anywhere; context: DSV08 proves conversion deterministic (2 runs byte-identical except header timestamp), so seeds are N/A for Osm2Odr — but still unbound |
| 12 | large_artifact_policy | ✅ present | `xodr_files_committed: true` + reason (L731-734, refreshed at 64139d3b) |

Also present (bonus): `map_id`, `readiness_state CRS_CONTRACT_READY_STRUCTURAL_UNREVIEWED`, `real_map_mutation_authorized: false`, `protected_artifacts_immutable: true`, `mutations` block (header_metadata_pin), `protected_paths_not_modified`, per-run `semantic_sha256 019fc30e…` + algorithm, `road_count 32710 / junction_count 3646 / signal_count 0 / lane_link_count 32040`, `control_points`, `elevation_metrics`, candidate `header_offset`, `visual` rejected-artifact sha256s.

## Recommendation (for coordinator, not applied)

Bind 4 fields to make the manifest fully self-contained: (4) converter profile → `osm_to_xodr_wrapper.py` variant sha256 (2678373C3AC9… per DSV02), (5) CARLA/Osm2Odr version string from the donor env, (6) CRS-contract hash → reference `C44V01_coordinate_contract` report sha256, (11) seed policy → "deterministic (DSV08): no seeds, pinned by DSV08 evidence". (8)/(9) can stay N/A-by-policy with an explicit `"not_in_selected_chain": true` marker.

**C55V01b gate impact: none blocking — all hashes needed for validation (OSM, XODR, semantic, CRS pin, vertical) are bound.**
