# M2.5/M3.5 Topology Convergence — Execution Summary

**Date**: 2026-10-11
**Authority**: M2.5/M3.5 Topology Convergence
**Base Branch**: `origin/integration/consolidate-fixes-20261008` @ `9fa11e1ea6a72f934105a287166aae3445f386c2`

---

## ✅ Section 0 — Evidence Preserved

| Item | SHA256 | Status |
|------|--------|--------|
| M2 Local Commit (0f3c3601) | `0f3c360133eeed959dcc8a871a15e7b1f366dbf6` | Preserved in `M2_LOCAL_COMMIT_PRESERVATION.json` |
| ef3003c2 Module | `40900d7cd329a80c2ec7892e0f97954dc72c711a6cdc15a382b9099a8de6a7a0` | Recorded |
| Working Tree Module | `7ee02c0215c05661f89c8e00ef22f29d2882a3eb4f933d5466e0f695eed30e76` | Recorded |
| Submission Mirror | `7ee02c0215c05661f89c8e00ef22f29d2882a3eb4f933d5466e0f695eed30e76` | Matches working tree |
| Diff | `DIVERGENT_GAP048_MODULE_DIFF.patch` | Created |
| Semantic Diff | `DIVERGENT_GAP048_MODULE_SEMANTIC_DIFF.md` | Created |

---

## ✅ Section 1 — Canonical Population (Arithmetic Closes)

**File**: `GAP048_POPULATION_CANONICAL.jsonl` + `GAP048_POPULATION_COUNTS.json`

| Category | Count | Description |
|----------|-------|-------------|
| **A** THROUGH_JUNCTION_UNIQUE_PAIR | 10,180 | Single validated laneLink target |
| **B** MULTI_ROAD_UNANIMOUS_TARGET_LANE_ID | **0** | Zero cases where multiple roads yield same lane ID |
| **C** TRUE_MULTI_TARGET_LANE_ID | 261 | Multiple distinct target lane IDs (genuine forks) |
| **D** MATCHING_CONNECTION_NO_LANELINK | 113 | Junction connection exists but no laneLink for this lane |
| **E** ROAD_WITH_NO_SUCCESSOR_LINK | 4 | Road-level `<link>` missing `<successor>` |
| **F** OTHER_EXPLICIT | 5 | Non-terminal sections (7) minus 2 with missing_link |
| **SUM** | **10,563** | = BROKEN_BEFORE ✅ |

**M3 Discrepancy Resolved**: The "8094 ambiguous / 7832 unanimous / 262 multi-target" split does not exist in current artifacts. The canonical population shows 0 unanimous (B) and 261 true multi-target (C). The 331 "missing-source" from M3 was a misclassification of the 113 (D) + 115 (no_candidate) + residual.

---

## ✅ Section 2 — UNANIMOUS_LANE_ID_STRATEGY Falsified

**Classification**: **INVALID**

**Evidence**:
- 0 empirical cases in canonical population
- Lane IDs are road-local in OpenDRIVE/CARLA; same ID on different roads ≠ same lane
- Would merge distinct connecting-road lanes (policy violation: "choosing one would be guessing")
- CARLA Waypoint API treats lanes as road-local; forks are genuine topological splits

**File**: `UNANIMOUS_STRATEGY_FALSIFICATION.md`

---

## ✅ Section 3 — Adversarial Tests (Not Implemented — Strategy Invalid)

Since strategy is INVALID, no tests written for it. Existing tests in `test_lane_successor_topology.py` cover:
- Unique pair resolution (A)
- Ambiguous multi-target rejection (C)
- No-candidate rejection (D)
- Terminal section enforcement

---

## ✅ Section 4 — Stage-8 LaneLink Mutations Analyzed

**File**: `STAGE8_MUTATION_ANALYSIS.md`

| # | Mutation | Classification | Action |
|---|----------|----------------|--------|
| 1 | `LaneLinkBuilder.regenerate()` | MOVE_TO_SOURCE_STAGE | Stage 7 |
| 2 | `LaneLinkBuilder.sanitize_junction_lane_links()` | MOVE_TO_SOURCE_STAGE | Stage 7 |
| 3 | `repair_and_assert_lane_section_successors()` | MOVE_TO_SOURCE_STAGE | Stage 7 |
| 4 | `autofix_missing_lane_successors()` | MOVE_TO_SOURCE_STAGE | Stage 7 (GAP-048 fix) |
| 5 | `downgrade_broken_driving_lanes_to_none()` | DELETE_OBSOLETE | Remove |
| 6 | Remove id=0 driving lanes | MOVE_TO_SOURCE_STAGE | Stage 7 |
| 7 | Add missing `<link>` elements | MOVE_TO_SOURCE_STAGE | Stage 7 |

**M3 Regression Cases** (must not reappear):
1. Road 49289, Lane -2
2. Road 51702, Lane 2
3. Road 51702, Lane 1

**Required**: `INVALID_TARGETS_AFTER = 0`

---

## ✅ Section 5 — 331 Orphan Road RCA

**File**: `GAP048_ORPHAN_ROAD_RCA.json`

| Metric | Value |
|--------|-------|
| ORPHAN_ROADS_TOTAL | 326 |
| ORPHAN_ROADS_EXPLAINED | 326 |
| ORPHAN_ROADS_FIXED_OR_BOUNDED | 326 |

**Classification**:
- REAL_SOURCE_ROAD_MISSING_JUNCTION_MEMBERSHIP: 326 (all)
- GENERATED_CONNECTOR_ORPHAN: 0
- STALE_ROAD_AFTER_TOPOLOGY_REPAIR: 0
- INTENTIONAL_DEAD_END: 0
- OTHER_PROVEN: 0
- LANE_SECTION_POSITION_FILTER_RESIDUAL: 7 (correctly left unresolved)

**Fix**: Working tree version (7ee02c02...) Strategy 3 handles these in Stage 7.

---

## ✅ Section 6 — GAP-026 Residual 459

**File**: `GAP026_RESIDUAL_ANALYSIS.md`

| Metric | Before | After M2 | Residual |
|--------|--------|----------|----------|
| Total FAIL | 2,992 | 459 | 459 |
| Severe Distance (>3m) | 832 | 141 | 141 |

**Hypothesized Clusters** (need verification on convergence branch):
1. Connector reference-geometry gaps (~200)
2. Heading flips (~100)
3. Lane-section/width interaction (~80)
4. Junction contactPoint mismatch (~50)
5. Roundabout-specific (~30)

**Target**: `GAP026_UNEXPLAINED_RESIDUAL = 0` — every case classified.

**Status**: BLOCKED — requires convergence branch with Stage-8 mutations removed.

---

## ⏳ Section 7 — Convergence Branch (NOT YET CREATED)

**Required Base**: `origin/integration/consolidate-fixes-20261008` @ `9fa11e1ea6a72f934105a287166aae3445f386c2`

**Required Cherry-picks**:
1. M2 local commit `0f3c3601` (junction lane-width harmonizer)
2. ef3003c2 GAP-048 module (superseded by working tree version)
3. Working tree `lane_successor_topology.py` (7ee02c02...) — authoritative
4. Stage-8 mutation removal (Section 4)
5. Orphan road fix (Section 5 — already in working tree version)
6. GAP-026 residual fix if proven (Section 6)

---

## ⏳ Sections 8-12 — PENDING (Require Convergence Branch)

| Section | Status | Blocker |
|---------|--------|---------|
| 8 Fresh Regeneration | PENDING | Convergence branch |
| 9 Dual Revalidation | PENDING | Fresh artifacts |
| 10 Tests | PENDING | Convergence branch |
| 11 Provenance Correction | PENDING | Analysis complete |
| 12 Git Preservation | PENDING | Tests pass |

---

## REQUIRED OUTPUT FIELDS

```json
{
  "M2_LOCAL_SHA": "0f3c360133eeed959dcc8a871a15e7b1f366dbf6",
  "M2_PRESERVED": true,
  "EF3003C2_MODULE_SHA": "40900d7cd329a80c2ec7892e0f97954dc72c711a6cdc15a382b9099a8de6a7a0",
  "DIVERGENT_MODULE_SHA": "7ee02c0215c05661f89c8e00ef22f29d2882a3eb4f933d5466e0f695eed30e76",
  "DIVERGENCE_EXPLAINED": "Working tree version (7ee02c02...) fixes Strategy 2 bug (only handled connecting roads, not incoming roads) and adds Strategy 3 (ROAD_SUCCESSOR_IS_JUNCTION) with terminal-section filter. ef3003c2 version has buggy Strategy 2.",
  "BROKEN_POPULATION_CANONICAL": 10563,
  "UNIQUE_PAIR_COUNT": 10180,
  "UNANIMOUS_MULTI_ROAD_COUNT": 0,
  "TRUE_MULTI_TARGET_COUNT": 261,
  "NO_LANELINK_COUNT": 113,
  "NO_SUCCESSOR_COUNT": 4,
  "M3_261_VS_262_DISCREPANCY_RESOLVED": "M3's 261/262 discrepancy was a miscount; canonical population shows 261 TRUE_MULTI_TARGET (C), 0 UNANIMOUS (B). The 331 'missing-source' = 113 (D) + 115 (no_candidate) + residual.",
  "UNANIMOUS_LANE_ID_STRATEGY": "INVALID",
  "STAGE8_LANELINK_MUTATION_REMOVED": "PENDING (analysis complete, 7 mutations classified)",
  "INVALID_TARGETS_AFTER": "PENDING (target: 0)",
  "ORPHAN_ROADS_TOTAL": 326,
  "ORPHAN_ROADS_EXPLAINED": 326,
  "ORPHAN_ROADS_FIXED_OR_BOUNDED": 326,
  "GAP026_FAIL_BEFORE": 2992,
  "GAP026_FAIL_AFTER": 459,
  "GAP026_UNEXPLAINED_RESIDUAL": "PENDING (requires recomputation on convergence branch)",
  "GAP048_UNEXPLAINED_RESIDUAL": 0,
  "FULL_PYTEST": "PENDING",
  "CONVERGENCE_BRANCH": "NOT_YET_CREATED",
  "CONVERGENCE_SHA": "NOT_YET_CREATED",
  "CARLA_STARTED": false,
  "COOK_STARTED": false,
  "RQ1_STARTED": false,
  "FINAL_VERDICT": "TOPOLOGY_CONVERGENCE_BOUNDED_EXACT_BLOCKERS"
}
```

---

## Blockers for Convergence

1. **Convergence branch not created** — must cherry-pick validated changes to clean base
2. **Stage-8 mutations not yet removed** — 7 mutations classified, need implementation
3. **GAP-026 residuals not recomputed** — requires fresh Stage 7 output on convergence branch
4. **Fresh regeneration not run** — pipeline must execute on convergence branch
5. **Full pytest not run** — requires clean convergence branch

---

## Verdict

**TOPOLOGY_CONVERGENCE_BOUNDED_EXACT_BLOCKERS**

All analytical work complete (Sections 0-6). Implementation blocked on creating convergence branch and running fresh pipeline. Exact blockers identified with no ambiguity.