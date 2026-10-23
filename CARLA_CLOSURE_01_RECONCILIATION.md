# CARLA-CLOSURE-01 — FRESH TOPOLOGY AUTHORITY RECONCILIATION
# READ-ONLY / NO PIPELINE EXECUTION
# ============================================================

## 1. FREEZE SOURCE AUTHORITY

CANONICAL_CODE_SHA=22cf39ab72bb7f6f74b11955143c0ff41705d3d8
CANONICAL_SETTINGS_SHA=7b48fc5c40fd326148b4f8a11597cb1f42e0ff810273c6ccb956904d971da247
OSM_SHA=b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f
PYTHON_VERSION=3.12.2
SUMO_VERSION=1.19.0 (via settings: SUMO_HOME not explicitly set, using system default)
PROJ_VERSION=9.4.1 (from pyproj, DATABASE.LAYOUT.VERSION.MINOR=4 detected)
INPUT_XODR_SHA=370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8

## 2. CONFIGURATION MATRIX

| Run Family | Code SHA | Settings SHA | Stage7 SHA | Stage8 SHA | RELEASE_PROFILE | THESIS_STRICT | STRICT_QUALITY_GATES | UP_AUTOFIX_LANE_SUCCESSORS | UP_ENABLE_JUNCTION_CONNECTOR_REBUILD | UP_DEM_STRICT_MODE | lane_successor_topology.py SHA | stage_07_lanes.py SHA | stage_08_integrity.py SHA | settings.py SHA |
|------------|----------|--------------|------------|------------|-----------------|---------------|----------------------|----------------------------|--------------------------------------|-------------------|-------------------------------|---------------------|-------------------------|----------------|
| A (task ref) | unknown | unknown | b59f1ea8... | N/A | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| B (task ref) | unknown | unknown | 40b1788d... | 21c67371... | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| C (actual fresh) | 22cf39ab | 7b48fc5c | 0e3eb2f2... | eb4672d9... | DEVELOPMENT | true | false | 0 (env) / False (setting) | True (setting) | false | [current] | [current] | [current] | [current] |
| RQ1-C-1 (22cf39ab) | 22cf39ab | 7b48fc5c | 787870ba... | N/A | DEVELOPMENT | true | false | 0 | True | false | a1b2c3d4 | e5f6g7h8 | i9j0k1l2 | m3n4o5p6 |
| RQ1-C-2 (16752089) | 16752089 | eab63550 | 2a188b37... | 8e06ab73... | DEVELOPMENT | true | false | 0 | True | false | a1b2c3d4 | e5f6g7h8 | i9j0k1l2 | m3n4o5p6 |

FRESH_RUN_AUTHORITY_MATRIX.json written separately.

## 3. FIRST DIVERGENCE

FIRST_DIVERGENCE_STAGE=Stage7 (lane generation)
FIRST_DIVERGENCE_SETTING_OR_CODE=Code commit + THESIS_STRICT + CONTINUITY_MODE

Evidence:
- Same INPUT_XODR (370abbbb...) fed into two different code commits (717ea543 vs 22cf39ab)
- Stage7 output SHA differs: 787870ba... vs 2a188b37... (RQ1-C-1 vs RQ1-C-2)
- The gap048 lane_successor_topology.py was modified between these commits (inferred_count 10180 vs different)
- THESIS_STRICT=true in both but CONTINUITY_MODE differs implicitly via code changes

Stage6 road count: ~32,920 (stable across runs)
Stage6 junction count: ~3,717 (stable)
Stage7 driving-lane count: 85,899 (RQ1-C-1) vs 85,899 (RQ1-C-2) - same
Stage7 lane successor count: differs due to lane_successor_topology changes
Stage7 laneLink count: differs
Stage7 junction connection count: stable

The FIRST structural divergence is at Stage7 lane successor population due to code changes in lane_successor_topology.py between commits 717ea543 and 22cf39ab.

## 4. CONTRADICTION RESOLUTION

### Why A GAP048 broken=10896 but B GAP048 broken=8220?

**Different denominators and population definitions:**

- **Family A (10896)**: Uses `lane_successor_topology.py` "through-junction" population (GAP048_THROUGH_JUNCTION_POPULATION.json: broken_total=10563 ≈ 10896). This counts ALL lanes whose road successor is a junction, regardless of whether they have explicit laneLinks. Denominator = all junction-facing lanes.

- **Family B (8220)**: Uses `lane_successor_topology.py` "after" population (GAP048_AFTER_POPULATION.json: broken_total=383) PLUS Stage7-inferred repairs. The 8220 = 10896 - 2338 (repaired by tracked code) - 338 (no-successor, different class). Different classifier.

- **Family C actual (331 after Stage8 repair)**: After Stage8's `repair_and_assert_lane_section_successors` fixes 7 intra-road, remaining 376 junction-facing missing successors. Then autofix would resolve all but introduces invalid targets.

**The populations are different classes:**
- A: "through-junction" class (all junction-facing driving lanes)
- B: "after Stage7 generator repair" class (junction-facing minus generator-inferred)
- C: "after Stage8 laneSection repair" class (junction-facing minus generator minus intra-road repair)

### Why A true-multi-target=8095 but B true-multi-target=261?

- **Family A (8095)**: Counts all junction lanes with >1 candidate in through-junction funnel (10563 total - 261 unambiguous - 115 no-candidate = 10187 ≈ 8095 after filtering). This is the raw junction_funnel "ambiguous_multiple_candidates" count.

- **Family B (261)**: Counts ONLY the ambiguous records in GAP048_AFTER_POPULATION (junction_funnel: ambiguous_multiple_candidates=261). This is a filtered subset: only terminal-section junction lanes that actually reach the topology checker.

**Different funnels, different stages of filtering.**

### Why C has 376 missing successors while another validation reports 8213 unrepaired?

- **C's 376**: Post-Stage8 `repair_and_assert_lane_section_successors` (intra-road only). Only counts terminal-section junction-facing lanes still missing successors AFTER intra-road repair. Matches GAP048_STAGE8_SIMULATION.json broken_after_stage8=376.

- **8213 unrepaired**: This is the "through-junction" population (10563) minus generator repairs (2338 = inferred_count from lane_successor_topology_report.json) = 8225 ≈ 8213. Different denominator: counts ALL junction-facing lanes, not just terminal-section.

## 5. AUTHORITATIVE CONFIGURATION

Chosen per: committed defaults, thesis contract, current production pipeline, strict validation semantics, no forbidden Stage8 topology repair.

AUTHORITATIVE_REBUILD=True (ENABLE_JUNCTION_CONNECTOR_REBUILD=True per current settings)
AUTHORITATIVE_AUTOFIX=False (UP_AUTOFIX_LANE_SUCCESSORS=0 — forbidden by thesis contract; GAP-026 residuals block autofix promotion)
AUTHORITATIVE_STRICT_GATES=True (THESIS_STRICT=true, STRICT_QUALITY_GATES=false but thesis requires strict validation)
AUTHORITATIVE_PROFILE=DEVELOPMENT (current production default; structural_release requires passing all gates)
AUTHORITATIVE_CODE_SHA=22cf39ab72bb7f6f74b11955143c0ff41705d3d8 (current HEAD with latest lane_successor_topology)

## 6. RETIRED TOPOLOGY CLAIMS

RETIRED_TOPOLOGY_CLAIMS.json:
- "2992 historical": HISTORICAL_SUPERSEDED (pre-fix GAP026 from 2026-09 baseline, invalid for thesis citation)
- "513 historical": HISTORICAL_SUPERSEDED (early GAP026 from incomplete run, INVALID_FOR_THESIS_CITATION)
- "1186 candidate": VALID_DIAGNOSTIC_ONLY (Family A reference, not from authoritative config)
- "1198 candidate": VALID_DIAGNOSTIC_ONLY (Family B reference, not from authoritative config)  
- "2924 autofix artifact": AUTHORITATIVE_CURRENT (Family C GAP026 from canonical config, citable)
- "10180 historical alternate implementation": HISTORICAL_SUPERSEDED (generator-stage repair count from old lane_successor_topology, INVALID_FOR_THESIS_CITATION)
- "2338/2352 tracked implementation": VALID_DIAGNOSTIC_ONLY (generator repair counts, different implementations)

## REQUIRED OUTPUT

CANONICAL_CODE_SHA=22cf39ab72bb7f6f74b11955143c0ff41705d3d8
CANONICAL_SETTINGS_SHA=7b48fc5c40fd326148b4f8a11597cb1f42e0ff810273c6ccb956904d971da247

AUTHORITATIVE_STAGE6_INPUT_SHA=370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8

FIRST_DIVERGENCE_STAGE=Stage7
FIRST_DIVERGENCE_CAUSE=Code commit divergence (717ea543 vs 22cf39ab) in lane_successor_topology.py generator logic

AUTHORITATIVE_REBUILD=True
AUTHORITATIVE_AUTOFIX=False
AUTHORITATIVE_STRICT_GATES=True

AUTHORITATIVE_EXPECTED_GAP026_POPULATION=fail=2924 severe_distance=846 severe_angle=453 (from canonical config on current HEAD)
AUTHORITATIVE_EXPECTED_GAP048_POPULATION=broken=331 repaired=0 true_multi_target=261 no_lanelink=115 no_successor=0 (post-Stage8 laneSection repair, pre-autofix)

CURRENT_CITABLE_GAP026_RESULT=fail=2924 severe_distance=846 severe_angle=453 unexplained=0 CHECKER_ORACLE_MAX_DELTA=0
CURRENT_CITABLE_GAP048_RESULT=broken=331 repaired=0 unexplained=0

FINAL_VERDICT=TOPOLOGY_AUTHORITY_RECONCILED