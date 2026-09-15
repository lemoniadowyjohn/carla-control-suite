# Large Committed Binaries Audit — 2026-09-15

**Audit date:** 2026-09-15 20:06 UTC+2
**Branch audited:** `integration/session-batch1-20260912` (HEAD `010e8ff6` → now `9f6226c2`)
**Method:** `git ls-files reports/ | grep -iE '\.xodr$|\.fbx$|\.glb$'` + `git cat-file -s` for blob sizes + `git lfs ls-files -s` for LFS object sizes

---

## Summary

| Category | Count | Git blob size (actual) | LFS object size (where applicable) |
|---|---|---|---|
| LFS-tracked `.xodr` | 20 | ~100 B each (pointer) | 81–109 MB each (1.76 GB total) |
| Non-LFS tiles `.xodr` | 4 | 0.6–2.2 MB each (5.1 MB total) | n/a |
| Non-LFS `demo_enriched_candidate_c7.xodr` | 1 | 3.0 MB | n/a |
| Non-LFS `.fbx` | 5 | 14 KB–15 MB | n/a |
| Non-LFS `.glb` | 4 | 4 KB–25 MB | n/a |
| **TOTAL** | **37** | **~48 MB in git pack** | **~1.86 GB in LFS store** |

---

## Group A — LFS-Tracked `.xodr` (20 files, 1.76 GB in LFS)

These files are committed as ~100-byte LFS pointer blobs in git. The actual content lives in the Git LFS object store. They inflate `size-pack` minimally but consume LFS server bandwidth on every clone/checkout.

| Path | LFS Size | Commit | Added | Age (d) | Referenced outside `reports/`? |
|---|---|---|---|---|---|
| `reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_actual_reprojection.xodr` | 81 MB | `5bf3ca98` | 2026-08-02 | 43 | Yes — `tests/quality/test_ingolstadt_coordinate_verification.py`, `ultimate_pipeline/dem/dem_crs_contract.py`, publication CSVs |
| `reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_alignment_transform_only.xodr` | 81 MB | `5bf3ca98` | 2026-08-02 | 43 | Yes — same publication tree + tests |
| `reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_correct_georeference.xodr` | 81 MB | `5bf3ca98` | 2026-08-02 | 43 | Yes — same publication tree + tests |
| `reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_metadata_only.xodr` | 81 MB | `5bf3ca98` | 2026-08-02 | 43 | Yes — same publication tree + tests |
| `reports/ingolstadt_map_quality_v2/work_package_02_connectivity/candidate_connectivity_repaired.xodr` | 89 MB | `c095fb90` | 2026-08-03 | 42 | Yes — publication CSVs + `EXTERNAL_ARTIFACT_MANIFEST.json` |
| `reports/post_audit_hardening/20260803T150000Z/candidate_f4_piecewise_profiles.xodr` | 107 MB | `31dcdb45` | 2026-08-03 | 42 | No live references outside `reports/` (self-referencing evidence only) |
| `reports/post_audit_hardening/20260803T160000Z/_f5_work_copy.xodr` | 107 MB | `28addd95` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260803T160000Z/candidate_f5_bounded_offsets.xodr` | 107 MB | `28addd95` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260803T170000Z/_f6_work_copy.xodr` | 107 MB | `11e055d5` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260803T170000Z/candidate_f6_seam_repaired.xodr` | 107 MB | `11e055d5` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260804T000000Z/candidate_g5_lane_types.xodr` | 109 MB | `2500bc76` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260804T020000Z/candidate_g6_junction_lanelinks.xodr` | 109 MB | `32cfc9fe` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260804T030000Z/candidate_g7_roadmarks.xodr` | 109 MB | `f1fb448b` | 2026-08-03 | 42 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260804T050000Z/candidate_h_signal_enrichment.xodr` | 109 MB | `63b7eb5d` | 2026-08-04 | 41 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260807T000000Z/candidate_crosswalk_enriched.xodr` | 83 MB | `2ec8927a` | 2026-08-08 | 37 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr` | 83 MB | `21ffc321` | 2026-08-07 | 38 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260807T000000Z/governed_payload.xodr` | 81 MB | `3e4e2d9a` | 2026-08-07 | 38 | Yes — `phase_q/governed_payload.py`, `govern_load_payload.py`, `stage_c2_govern_promote.py` |
| `reports/post_audit_hardening/20260807T000000Z/perception_governed/governed_payload.xodr` | 83 MB | `74fb5b4d` | 2026-08-08 | 37 | Yes — `campaigns/.../manifest.json`, `docs/N04_CLAUDE_C0_PACKET.md`, `docs/N19_CLAUDE_C1_PACKET.md` |
| `reports/post_audit_hardening/20260809T000000Z_C1_GENERATION/candidate_crosswalk_enriched.xodr` | 81 MB | `8b400351` | 2026-08-09 | 36 | No live references outside `reports/` |
| `reports/post_audit_hardening/20260809T000000Z_C2_3DPACKAGE/perception_governed/governed_payload.xodr` | 81 MB | `28417538` | 2026-08-09 | 36 | No live references outside `reports/` |

---

## Group B — Non-LFS Tiles (4 files, 5.1 MB total)

These are committed directly in git as real blobs. They are not LFS-tracked (no matching `.gitattributes` rule).

| Path | Blob Size | Commit | Added | Age (d) | Referenced outside `reports/`? |
|---|---|---|---|---|---|
| `reports/post_audit_hardening/20260804T060000Z/tiles/tile_0_0.xodr` | 2,234.8 KB | `7c636d8c` | 2026-08-04 | 41 | No (generic `tile_0_0` name matches code but not this specific artifact) |
| `reports/post_audit_hardening/20260804T060000Z/tiles/tile_0_1.xodr` | 688.3 KB | `7c636d8c` | 2026-08-04 | 41 | No |
| `reports/post_audit_hardening/20260804T060000Z/tiles/tile_1_0.xodr` | 638.9 KB | `7c636d8c` | 2026-08-04 | 41 | No |
| `reports/post_audit_hardening/20260804T060000Z/tiles/tile_1_1.xodr` | 1,515.4 KB | `7c636d8c` | 2026-08-04 | 41 | No |

---

## Group C — Non-LFS `demo_enriched_candidate_c7.xodr` (3.0 MB)

| Path | Blob Size | Commit | Added | Age (d) | Referenced outside `reports/`? |
|---|---|---|---|---|---|
| `reports/post_audit_hardening/C7_ENRICHMENT_EVIDENCE/demo_enriched_candidate_c7.xodr` | 3,049.2 KB | `87d868ca` | 2026-08-16 | 30 | Yes — `reports/post_audit_hardening/C7_ENRICHMENT_COMPLETENESS.md` (within `reports/` only) |

---

## Group D — Non-LFS FBX/GLB Window-OSM Copies (6 files, ~55 KB total)

Three duplicate sets of `.fbx`/`.glb` from the Aug 4 Phase-J OSM2World→Blender pipeline runs.

| Path | Blob Size | Commit | Added | Age (d) | Referenced outside `reports/`? |
|---|---|---|---|---|---|
| `reports/post_audit_hardening/20260804T125500Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx` | 14.3 KB | `a386ba90` | 2026-08-04 | 41 | Yes — local provenance manifests |
| `reports/post_audit_hardening/20260804T125500Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb` | 4.0 KB | `a386ba90` | 2026-08-04 | 41 | Yes — local provenance manifests |
| `reports/post_audit_hardening/20260804T130959Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx` | 14.3 KB | `a386ba90` | 2026-08-04 | 41 | Yes — local provenance manifests |
| `reports/post_audit_hardening/20260804T130959Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb` | 4.0 KB | `a386ba90` | 2026-08-04 | 41 | Yes — local provenance manifests |
| `reports/post_audit_hardening/20260804T185517Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.fbx` | 14.3 KB | `f5aabc0a` | 2026-08-04 | 41 | Yes — local provenance manifests |
| `reports/post_audit_hardening/20260804T185517Z/artifacts/ingolstadt_cooked_perception_v1_b9e07465_window_osm.glb` | 4.0 KB | `f5aabc0a` | 2026-08-04 | 41 | Yes — local provenance manifests |

---

## Group E — Non-LFS FBX/GLB (Today's New Artifacts, ~40 MB total)

The "new FBX artifacts committed today" referenced in the prompt. These are committed directly into git and represent the largest non-LFS binary burden on the pack.

| Path | Blob Size | Commit | Added | Age (d) | Referenced outside `reports/`? |
|---|---|---|---|---|---|
| `reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/artifacts/ingolstadt_cooked_perception_v1_b9e07465_full_pin.fbx` | 145.7 KB | `c8108eca` | 2026-09-15 | 0 | Yes — local `README.md`, `SUMMARY.json`, `fbx_roundtrip_manifest.json` |
| `reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/artifacts/scene.glb` | 179.5 KB | `c8108eca` | 2026-09-15 | 0 | Yes — local `README.md`, `SUMMARY.json` |
| `reports/production_readiness/20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX/artifacts/ing_f3e82001_merged.fbx` | 15,132.8 KB (14.8 MB) | `c59c390d` | 2026-09-15 | 0 | Yes — local `README.md`, `SUMMARY.json`, blender manifests, `run_blender.py`, `run_roundtrip.py` |
| `reports/production_readiness/20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX/artifacts/osm2world/ingolstadt_cooked_perception_v1_merged_full_pin.glb` | 25,405.6 KB (24.8 MB) | `c59c390d` | 2026-09-15 | 0 | Yes — local `SUMMARY.json`, `osm2world_run_result.json`, `run_osm2world.py`, `run_roundtrip.py` |

---

## Group F — Unclassified (`perception_governed/governed_payload.xodr` 2× in Group A)

Included in Group A above — listed twice because there are two distinct copies at different paths.

---

## Notes

1. **No `.blend` files** are tracked under `reports/` (confirmed via `git ls-files`).
2. The `.fbx`/`.glb` from the tile-based FBX generation probe (`20260915T171346Z_TILE_BASED_FBX_GENERATION_PROBE`) are **gitignored** (`artifacts/.gitignore`) and not counted.
3. **LFS pointer note:** The 20 LFS-tracked `.xodr` files each have a ~100-byte pointer blob in git but 81–109 MB in LFS storage. Total LFS consumption for `reports/`: **~1.76 GB**.
4. **Today's non-LFS FBX/GLB** (Group E) contributed **~40 MB** of new git pack size.
5. An incomplete version of this audit was committed as `088a1822` by a concurrent agent on `feature/full-grid-tile-fbx-cook-v1-20260915` — that version had empty size columns. See Task D for collision details.
