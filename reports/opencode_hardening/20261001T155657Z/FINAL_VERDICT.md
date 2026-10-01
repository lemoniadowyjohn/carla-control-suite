# FINAL VERDICT

**Repository**: lemoniadowyjohn/carla-control-suite
**Branch**: `fix/p0-coordinate-frame-tile-placement-authority-20261001`
**Baseline SHA**: `f897e0eb747ac827941ac4883170a5181a603111`
**Worktree**: `F:\p0-coord-frame-tile-placement-20261001`
**Generated**: 2026-10-01T21:30:00Z

---

## OVERALL VERDICT: `PARTIAL_WITH_EXACT_BLOCKERS`

| Defect | Status | Notes |
|--------|--------|-------|
| **P0-A** Tile Placement | `PARTIAL_WITH_EXACT_BLOCKERS` | 20/20 tiles cooked successfully; explicit placement transforms bound (architecture B); manifest validation PASS; true world placement blocked by irreducible OSM2World render-vs-footprint offset |
| **P0-B** CRS Metadata | `PASS` | Registry repaired with structured CRS fields + schema validation |
| **P1-C** Coordinate Authority | `PASS` | Single canonical module with 8 APIs, frame IDs, units, axis order, CRS strings, rebase, map SHA, version |
| **P1-D** C29 Compensation | `PASS` | Stale double-compensation neutralized; defaults to (0,0); patch script deprecated |
| **P1-E** Frame Semantics | `PASS` | Frame relationships codified; EPSG:32632 correctly distinct |

---

## ROOT CAUSE (P0-A)

**OSM2World auto-centers every tile's mesh on its own rendered bbox.** Measured `max |bbox_center_x| = 0.0000 m` across all 20 tiles. That world translation is never recorded in any tile manifest, so each tile's world position is undefined and unrecoverable from the shipped artifacts. This contradicts `tile_fbx_generator.py:1059-1061` which claims no re-centering occurs.

**The 485.84 m figure is NOT a validated placement error.** It is a metric defect:
- Algebraic identity: `seam_6,6<->7,6 = 237.36 - 8.93 = 228.43 m` — exactly the difference between two tiles' building-population offsets from their cell centres.
- Blindness test: injecting a 50 m placement error into tile 6,8 changed only 3/31 pairs; max seam delta stayed 485.84 m (unchanged).
- The metric measures real building-distribution asymmetry, not placement error.

**Zero placement is definitively wrong** — placing at `(0,0)` lands geometry ~9145 m from the map of record.

**The source-node bbox center the checker substitutes for the true anchor is measurably wrong.** Best registration residual against map-of-record: H1 (checker assumption) = 18.6 m median / 218 m worst; H2 (registration) = 7.0 m median / 40 m worst.

---

## ARCHITECTURE DECISION: B (Explicit Placement Transform in Manifest)

- **A (bake into geometry)**: not pursued; OSM2World/Blender re-cook would mutate artifacts
- **B (mandatory explicit transform in manifest)**: implemented; transform recorded in every tile manifest, validated against canonical frame contract

---

## 20/20 TILES COOKED SUCCESSFULLY

| Metric | Value |
|--------|-------|
| Tiles attempted | 20 |
| Tiles OK | 20 |
| Tiles failed | 0 |
| Roundtrip pass | 20 |
| Wall clock | 596.5s |

**Fixes applied for full cook:**
- **OSM2World duplicate `type` tag fix**: Preprocessing step `_fix_osm_duplicate_type_tags()` removes duplicate `type=multipolygon` tags in multipolygon relations (OSM data quality issue affecting dense tiles)
- **Explicit placement transforms**: Every tile manifest now carries `placement` field with authoritative translation, binding hashes, frame IDs, and authority notes

---

## PLACEMENT TRANSFORM BINDING

Every tile manifest now carries a `placement` field:

```json
{
  "schema_version": "1.0.0",
  "map_of_record_sha256": "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8",
  "tile_index": [6, 8],
  "source_osm_sha256": "<computed>",
  "exported_fbx_sha256": "<from manifest.fbx.sha256>",
  "source_frame": "NATIVE",
  "target_frame": "LOCAL",
  "translation_local_m": [6604.09, 8502.43],
  "translation_bbox_center_source_local_m": [6604.09, 8502.41],
  "translation_bbox_center_exported_local_m": [0.00, -0.02],
  "authority": "source_osm_bbox_center_minus_exported_mesh_bbox_center"
}
```

Validation: recorded translation matches recomputed authority (source bbox center - exported bbox center) within 10m tolerance (error = 0 by construction).

---

## BLOCKER: TRUE WORLD PLACEMENT NOT CERTIFIABLE AT 10 m

The recorded authority (source footprint bbox center) is **not** the true rendered mesh anchor. OSM2World centers on the *rendered* geometry bbox (walls extend beyond footprints), creating an irreducible offset of up to ~40m worst case between the recorded authority (source footprint bbox center) and the true rendered geometry anchor. This is NOT a threshold issue; the 10m threshold is preserved. No re-cook was possible without mutating artifacts (violating 'no map mutation' rule).

Therefore: **true world placement cannot be certified at the 10 m threshold.** The verdict is honestly `PARTIAL_WITH_EXACT_BLOCKERS`.

---

## EVIDENCE BUNDLE

All files in `reports/opencode_hardening/20261001T155657Z/`:

| File | Description |
|------|-------------|
| `BASELINE_AUTHORITY.json` | Immutable repo/branch/map identities; preflight results; tool availability |
| `CRS_AUTHORITY_CALL_GRAPH.json` | 5 bare + 3 expanded tmerc duplicates; 6 rebase literals; required APIs |
| `CRS_CONTRACT_BEFORE_AFTER.json` | Diff: no canonical module → canonical module + refactored consumers + registry repair |
| `PRE_C29_COMPENSATION_AUDIT.json` | Stale `building_frame_shift_to_auto_local` returns non-zero; patch script deprecated |
| `TILE_ORIGIN_ROOT_CAUSE.json` | **Primary root cause document** — proofs 1-4, metric defect, missing fields, stale docs |
| `TILE_PLACEMENT_BEFORE_AFTER.json` | 20/20 tiles PASS manifest validation; blocker noted |
| `TILE_NEGATIVE_CONTROLS.json` | All 12 controls REJECTED (zero, double, wrong index/rebase/hash/FBX, xy_swap, y_reflection, 100x/0.01x scale, EPSG:32632-as-native, stale version) |
| `TEST_RESULTS.json` | 8 test suites: 7 PASS, 1 PARTIAL_WITH_EXACT_BLOCKERS |
| `FINAL_VERDICT.json` | This verdict in machine-readable form |
| `FINAL_VERDICT.md` | This document |

---

## REPRODUCTION

```bash
# In isolated worktree
git worktree add -b fix/p0-coordinate-frame-tile-placement-authority-20261001 \
  F:\p0-coord-frame-tile-placement-20261001 f897e0eb747ac827941ac4883170a5181a603111

# Verify map
python -c "from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map; print(verify_pinned_map('auto_map_of_record'))"

# Run checker
$env:PYTHONPATH = "F:\p0-coord-frame-tile-placement-20261001"
python tools/tile_frame_consistency.py \
  --cook-results "reports/production_readiness/20261001T211557Z_FULL_GRID_TILE_FBX_COOK/COOK_RESULTS.json" \
  --out reports/opencode_hardening/20261001T155657Z/TILE_PLACEMENT_BEFORE_AFTER.json
```

---

## COMPLIANCE CHECKLIST

- [x] No production branch modified
- [x] No map mutation (pinned map SHA/bytes unchanged)
- [x] 10 m threshold unchanged
- [x] Single architecture (B) implemented
- [x] All negative controls REJECTED
- [x] Full real-tile validation (20/20 tiles)
- [x] Evidence bundle complete with exact filenames
- [x] No Unreal/CARLA runtime success claimed
- [x] Final verdict fields exact: `verdict=PARTIAL_WITH_EXACT_BLOCKERS`, `max world-placement/seam error` reported as blocker not number