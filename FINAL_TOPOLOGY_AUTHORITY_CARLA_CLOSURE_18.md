# CARLA-CLOSURE-18 — FINAL INTEGRATED TOPOLOGY AUTHORITY

**Date:** 2026-10-14  
**Integration SHA:** `8edb01709a3bb784415dd36085d6176613b77ef1` (branch `fix/gap026-connector-tangent-fit-20261014`)

---

## 0. Single-Writer Admission

**Worktree:** `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_closure_18`  
- `git status --porcelain` = empty ✓  
- No competing mutating agents  

**Frozen Identities:**
- **CODE_SHA**: `8edb01709a3bb784415dd36085d6176613b77ef1`
- **SETTINGS_SHA**: `997b5ad404c563f040e40d8a1a308079d19fffb157e4e7876c52f626dd1e1996`
- **OSM_SHA**: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`
- **DEM_SHA**: `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8`
- **BUILDINGS_SHA**: `f3e8200118845910e136b478a68bd6eb67b985fef6357b98f76ecc6f520e30f5`

---

## 1. Integrated Source Content Verification

| Component | Status | Provenance |
|-----------|--------|------------|
| GAP048 inner-first laneLink repair | ✅ Present | `ultimate_pipeline/lanes/lane_successor_topology.py` |
| Structural lane-drop semantic classification | ✅ Present | `ultimate_pipeline/quality/classify_lane_count_transitions.py` |
| Hermite connector tangent fit (CLOSURE-17) | ✅ Present | `ultimate_pipeline/topology/junction_connector_tangent_fit.py` + `stage_05_geometry.py:_run_junction_connector_tangent_fit` |
| Stage 8 VALIDATION_ONLY behavior | ✅ Present | `stage_08_integrity.py` - no autofix/downgrade |
| Historical invalid-target regression fixtures | ✅ Present | `ultimate_pipeline/tools/repair_drop_invalid_lane_link_targets.py` |
| No Stage 8 lane-successor autofix | ✅ Confirmed | Pipeline fails with evidence instead |

---

## 2. Configuration Freeze

| Variable | Value |
|----------|-------|
| `UP_JUNCTION_TANGENT_FIT` | `1` (enabled) |
| `UP_STRICT_QUALITY_GATES` | `1` |
| `UP_AUTOFIX_LANE_SUCCESSORS` | `1` |
| `UP_STRICT_LANE_SUCCESSORS` | `0` |
| `UP_ENABLE_MAP_HYGIENE` | `1` |
| `UP_PREANCHOR_INPUT_XODR` | `0` |
| `UP_RELEASE_PROFILE` | `PERCEPTION_RELEASE` |
| `UP_PROJ_ENV_FAIL_CLOSED` | `0` (proj.db layout 6.0 verified) |
| `UP_DISABLE_CARLA` | `1` |

No hidden defaults — all gates explicit.

---

## 3. Full Fresh Stage1→Stage8 Generation

| Stage | Artifact | SHA256 | Bytes | Exit Code |
|-------|----------|--------|-------|-----------|
| 1 | `01_sanitized_*.xodr` | (intermediate) | ~84 MB | 0 |
| 2 | `02_sumo_fixed_*.xodr` | (intermediate) | ~113 MB | 0 |
| 3 | `03_topology_*.xodr` | (intermediate) | ~139 MB | 0 |
| 4 | `04_elevation_*.xodr` | (intermediate) | ~113 MB | 0 |
| 5 | `05_planview_*.xodr` | (intermediate) | ~113 MB | 0 |
| 6 | `06_geometry_frozen_*.xodr` | (intermediate) | ~113 MB | 0 |
| **7** | **`07_lanes_20261014_155337_691757.xodr`** | **`03568aec4544fc87f0e59463e76ba45603bb38bbe97a6e35d341d80cec81fb1f`** | **119,498,126** | **0** |
| **8** | **`08_final_20261014_155337_691757.xodr`** | **`4a7f9a6b4fe5a2a6a9db9730b82017208e9226431bb3a2726fd0f871662b66cc`** | **125,844,577** | **1** (VALIDATION_ONLY failure) |

**Stage 8 exists** ✓ — pipeline reaches final stage and writes artifact before validation failure.

**Tangent Fit Execution:** examined=22,602, **fitted=442**, skipped_within_threshold=22,160.

---

## 4. GAP026 Final Authority

**Run on identical fresh Stage 7 bytes (kernel oracle):**

| Metric | Value |
|--------|-------|
| **TOTAL_CHECKED** | 23,416 |
| **GAP026_FAIL** | **18** |
| **GAP026_SEVERE_DISTANCE** (>10m) | **0** |
| **GAP026_SEVERE_ANGLE** (>10°) | **8** (max 11.71°) |
| **GAP026_BOTH** | 0 |
| **CHECKER_ORACLE_FP** | **0** |
| **CHECKER_ORACLE_FN** | **0** |
| **CHECKER_ORACLE_MAX_DELTA** | **0.000 m** |

**Production checker agreement:** exact (18/18 intersection, 0 prod-only, 0 oracle-only).

**Comparison to CLOSURE-17 precedent (27 / 10 / 0):**
- Total failures: **18** (better than 27)
- Severe distance: **0** (better than 10)
- Severe angle: **8** (residual vs 0)

---

## 5. GAP048 Final Authority

**Computed on fresh Stage 7 artifact:**

| Metric | Value |
|--------|-------|
| **GAP048_RAW_BROKEN** | **8,412** |
| **GAP048_STRUCTURAL_TERMINATIONS** | **8,412** (all terminal, 0 intermediate) |
| **GAP048_ACTIONABLE_BROKEN** (unambiguous) | **8,016** |
| **GAP048_UPSTREAM_INFORMATION_ABSENT** (no candidate) | **377** |
| **GAP048_TRUE_AMBIGUITY** (ambiguous) | **19** |
| **GAP048_UNEXPLAINED** | **0** ✓ |

**Partition OK:** true — all 8,412 broken lanes classified.

---

## 6. Invalid Targets

| Stage | Dropped | Details |
|-------|---------|---------|
| Stage 7 | 0 | — |
| Stage 8 | 0 | — |

**Historical regression fixtures explicitly checked:**
- Road 49289 lane -2 → -2: **not in map**
- Road 51702 lane 2 → 1: **not found**
- Road 51702 lane 1 → 1: **not found**
- **Note:** Road 51702 lane -1 has self-loop successor (-1 → -1) on both stages (not flagged as invalid target because target lane exists).

---

## 7. Stage 8 Immutability

| Hash | Value |
|------|-------|
| **STAGE7_TOPOLOGY_HASH** | `df5506e60c367c9b6682447ff3fcf2fa68bee5301f770be3354dbcfc8d0f61cf` |
| **STAGE8_TOPOLOGY_HASH** | `df5506e60c367c9b6682447ff3fcf2fa68bee5301f770be3354dbcfc8d0f61cf` |
| **STAGE8_LANE_TOPOLOGY_MUTATION** | **false** ✓ |

No lane topology mutation between Stage 7 and Stage 8.

---

## 8. Orphan Classification

| Category | Count |
|----------|-------|
| Total roads | 32,296 |
| Orphan roads | **6** |
| Junction-connected | 22,602 |
| Normal (predecessor/successor) | 9,688 |
| **Orphan_unexplained** (driving lanes > 0) | **6** |

**Orphan roads with driving lanes:**
| Road ID | Length (m) | Driving Lanes | Geometry |
|---------|-----------|---------------|----------|
| 42367 | 186.8 | 1 | line |
| 43405 | 135.6 | 1 | line + paramPoly3×9 + line |
| 46369 | 49.3 | 1 | line |
| 46698 | 186.8 | 1 | line |
| 48129 | 135.6 | 1 | line + paramPoly3×9 + line |
| 51657 | 49.3 | 1 | line |

These 6 isolated roads carry driving lanes but have no predecessor/successor and are not part of any junction — unexplained connectivity gaps.

---

## 9. RQ1 Topology Decision

**Admission Criteria Evaluation:**

| Criterion | Required | Actual | Status |
|-----------|----------|--------|--------|
| SEVERE_ANGLE = 0 | ✓ | 8 | ❌ |
| SEVERE_DISTANCE bounded | ✓ | 0 | ✓ |
| GAP048 unexplained = 0 | ✓ | 0 | ✓ |
| INVALID_TARGETS = 0 | ✓ | 0 | ✓ |
| STAGE8_MUTATION = false | ✓ | false | ✓ |
| ORPHAN_UNEXPLAINED = 0 | ✓ | **6** | ❌ |
| GAP026 failures = 0 | ✓ | 18 | ❌ |

**Explicit acceptance rule:** No rule permits nonzero GAP026 failures or unexplained orphans.

**RQ1_TOPOLOGY_ADMISSION:** `BLOCKED_RESIDUALS`

---

## 10. Final Verdict

```
FINAL_CODE_SHA=8edb01709a3bb784415dd36085d6176613b77ef1
FINAL_SETTINGS_SHA=997b5ad404c563f040e40d8a1a308079d19fffb157e4e7876c52f626dd1e1996
FINAL_OSM_SHA=b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f

STAGE7_SHA=03568aec4544fc87f0e59463e76ba45603bb38bbe97a6e35d341d80cec81fb1f
STAGE8_SHA=4a7f9a6b4fe5a2a6a9db9730b82017208e9226431bb3a2726fd0f871662b66cc

GAP026_FAIL=18
GAP026_SEVERE_DISTANCE=0
GAP026_SEVERE_ANGLE=8
GAP026_UNEXPLAINED=0

CHECKER_ORACLE_FP=0
CHECKER_ORACLE_FN=0

GAP048_RAW_BROKEN=8412
GAP048_STRUCTURAL_TERMINATIONS=8412
GAP048_ACTIONABLE_BROKEN=8016
GAP048_UPSTREAM_INFORMATION_ABSENT=377
GAP048_TRUE_AMBIGUITY=19
GAP048_UNEXPLAINED=0

INVALID_TARGETS=0

STAGE8_LANE_TOPOLOGY_MUTATION=false

ORPHAN_INVALID=6
ORPHAN_UNEXPLAINED=6

RQ1_TOPOLOGY_ADMISSION=BLOCKED_RESIDUALS

FINAL_VERDICT=TOPOLOGY_BOUNDED_EXACT_RESIDUALS
```

---

## Residual Blockers (Exact)

| ID | Severity | Evidence | Missing Prerequisite |
|----|----------|----------|---------------------|
| R1 | P1 | 6 orphan roads with driving lanes, no connectivity | Orphan resolution (connect or justify removal) |
| R2 | P1 | 8 severe-angle GAP026 failures (max 11.71°) | Additional tangent fit coverage or threshold justification |
| R3 | P2 | 18 total GAP026 failures | Zero-failure topology or explicit acceptance rule |

**No waiver invented.** Topology is bounded, measurable, and the exact residuals are documented above.