# Large Committed Binaries Audit - 2026-09-15

**Total files**: 37 (all `.xodr`, `.fbx`, `.glb` under `reports/`)
**Total size**: ~1.79 GB

## Files Orphaned (no live references outside `reports/`)

These are historical snapshots from early-August 2026 pipeline phases. No code or docs outside `reports/` reference these files.

| Path | Size | Commit | Phase | Days Ago |
|------|------|--------|-------|----------|
| reports/post_audit_hardening/20260803T150000Z/candidate_f4_piecewise_profiles.xodr | | 31dcdb45 | F | ~43 |
| reports/post_audit_hardening/20260803T160000Z/_f5_work_copy.xodr | | 28addd95 | F | ~43 |
| reports/post_audit_hardening/20260803T160000Z/candidate_f5_bounded_offsets.xodr | | 28addd95 | F | ~43 |
| reports/post_audit_hardening/20260803T170000Z/_f6_work_copy.xodr | | 11e055d5 | F | ~43 |
| reports/post_audit_hardening/20260803T170000Z/candidate_f6_seam_repaired.xodr | | 11e055d5 | F | ~43 |
| reports/post_audit_hardening/20260804T000000Z/candidate_g5_lane_types.xodr | | 2500bc76 | G | ~42 |
| reports/post_audit_hardening/20260804T020000Z/candidate_g6_junction_lanelinks.xodr | | 32cfc9fe | G | ~42 |
| reports/post_audit_hardening/20260804T030000Z/candidate_g7_roadmarks.xodr | | f1fb448b | G | ~42 |
| reports/post_audit_hardening/20260804T050000Z/candidate_h_signal_enrichment.xodr | | 63b7eb5d | H | ~42 |
| reports/post_audit_hardening/20260804T060000Z/tiles/tile_0_0.xodr | | 7c636d8c | I | ~42 |
| reports/post_audit_hardening/20260804T060000Z/tiles/tile_0_1.xodr | | 7c636d8c | I | ~42 |
| reports/post_audit_hardening/20260804T060000Z/tiles/tile_1_0.xodr | | 7c636d8c | I | ~42 |
| reports/post_audit_hardening/20260804T060000Z/tiles/tile_1_1.xodr | | 7c636d8c | I | ~42 |
| reports/post_audit_hardening/20260804T125500Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx | | a386ba90 | J | ~42 |
| reports/post_audit_hardening/20260804T125500Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb | | a386ba90 | J | ~42 |
| reports/post_audit_hardening/20260804T130959Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx | | a386ba90 | J | ~42 |
| reports/post_audit_hardening/20260804T130959Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb | | a386ba90 | J | ~42 |
| reports/post_audit_hardening/20260804T185517Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx | | f5aabc0a | J-rerun | ~42 |
| reports/post_audit_hardening/20260804T185517Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb | | f5aabc0a | J-rerun | ~42 |
| reports/post_audit_hardening/20260807T000000Z/candidate_crosswalk_enriched.xodr | | 25104180 | R13 | ~39 |
| reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr | | 21ffc321 | H | ~39 |
| reports/post_audit_hardening/20260807T000000Z/governed_payload.xodr | | 3e4e2d9a | H | ~39 |
| reports/post_audit_hardening/20260807T000000Z/perception_governed/governed_payload.xodr | | 74fb5b4d | Stage 16 | ~39 |
| reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13_scratch/guard_ok.xodr | | 25104180 | R13 | ~38 |
| reports/post_audit_hardening/20260808T000000Z_C0_REMEDIATION/R13_scratch/guard_tampered.xodr | | 25104180 | R13 | ~38 |
| reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/candidate_crosswalk_enriched.xodr | | 8b400351 | C1 | ~37 |
| reports/post_audit_hardening/20260809T000000Z_C2_3DPACKAGE/perception_governed/governed_payload.xodr | | 28417538 | C2 | ~37 |
| reports/post_audit_hardening/C7_ENRICHMENT_EVIDENCE/demo_enriched_candidate_c7.xodr | | 87d868ca | C7 | ~37 |
| reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_actual_reprojection.xodr | | 2cb2a4c4 | coord-truth | ~51 |
| reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_alignment_transform_only.xodr | | 2cb2a4c4 | coord-truth | ~51 |
| reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_correct_georeference.xodr | | 2cb2a4c4 | coord-truth | ~51 |
| reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_metadata_only.xodr | | 2cb2a4c4 | coord-truth | ~51 |
| reports/ingolstadt_map_quality_v2/work_package_02_connectivity/candidate_connectivity_repaired.xodr | | c095fb90 | connectivity | ~51 |

## Files with Live References (point to current production readiness)

These files are referenced by the current production readiness regen and have active pointers elsewhere:

| Path | Size | Commit | Notes |
|------|------|--------|-------|
| reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/artifacts/ingolstadt_cooked_perception_v1_b9e07465_full_pin.fbx | | c8108eca | Regenerated FBX at full-pin scale, supersedes run_11 |
| reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/artifacts/scene.glb | | c8108eca | Regenerated GLB at full-pin scale, supersedes run_11 |
| reports/production_readiness/20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX/artifacts/ing_f3e82001_merged.fbx | | c59c390d | Feat: convert+merge real building footprints into visual-clutter FBX |
| reports/production_readiness/20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX/artifacts/osm2world/ingolstadt_cooked_perception_v1_merged_full_pin.glb | | c59c390d | Glb counterpart of merged FBX above |

**Orphaned count**: ~30 files (early-August 2026 pipeline phases)
**With live references**: 4 files in `production_readiness/20260915T*`