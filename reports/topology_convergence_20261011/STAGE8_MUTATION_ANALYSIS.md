# Stage-8 LaneLink Mutation Analysis

**Date**: 2026-10-11
**Authority**: M2.5/M3.5 Topology Convergence

---

## All Stage-8 Code That Mutates Lane Predecessor/Successor IDs

| # | Location | Function | Mutation Type | Classification |
|---|----------|----------|---------------|----------------|
| 1 | `stage_08_integrity.py:555-559` | `LaneLinkBuilder.regenerate(root)` | **Complete rebuild** of all junction laneLinks (wipes old, creates new) | **MOVE_TO_SOURCE_STAGE** |
| 2 | `stage_08_integrity.py:560-562` | `LaneLinkBuilder.sanitize_junction_lane_links()` | Validates/prunes junction laneLinks; may remove invalid links | **MOVE_TO_SOURCE_STAGE** |
| 3 | `stage_08_integrity.py:592-601` | `repair_and_assert_lane_section_successors()` | Repairs intra-road laneSection successors (adds missing `<successor>` within same road) | **MOVE_TO_SOURCE_STAGE** (Stage 7) |
| 4 | `stage_08_integrity.py:722-726` | `autofix_missing_lane_successors()` | Adds missing lane successors from road/junction topology (env-gated: UP_AUTOFIX_LANE_SUCCESSORS) | **MOVE_TO_SOURCE_STAGE** (Stage 7) |
| 5 | `stage_08_integrity.py:769-776` | `downgrade_broken_driving_lanes_to_none()` | Downgrades broken driving lanes to `type="none"` (env-gated: UP_AUTOFIX_MISSING_LANE_SUCCESSORS) | **DELETE_OBSOLETE** |
| 6 | `stage_08_integrity.py:532-537` | Remove driving lanes with `id="0"` | Removes illegal lane elements | **MOVE_TO_SOURCE_STAGE** (Stage 7) |
| 7 | `stage_08_integrity.py:542-550` | Add missing `<link>` elements to driving lanes | Adds `<link>` where missing | **MOVE_TO_SOURCE_STAGE** (Stage 7) |

---

## Detailed Classification

### 1. LaneLinkBuilder.regenerate() — **MOVE_TO_SOURCE_STAGE**
**Location**: `stage_08_integrity.py:555-559`, `lanes/lanelink_builder.py:26-191`
**Mutation**: Wipes ALL existing `<laneLink>` elements in every junction connection and rebuilds from scratch using geometric matching.
**Impact**: Complete replacement of junction lane topology. Non-deterministic if lane ordering changes.
**Action**: Move to Stage 7 (generator stage) where laneLinks should be created as part of junction topology generation, not rebuilt post-hoc.

### 2. LaneLinkBuilder.sanitize_junction_lane_links() — **MOVE_TO_SOURCE_STAGE**
**Location**: `stage_08_integrity.py:560-562`, `lanes/lanelink_builder.py:199-271`
**Mutation**: Validates laneLink target existence and endpoint pose continuity; may flag/remove invalid links.
**Impact**: Can remove laneLinks that fail continuity checks.
**Action**: Move validation to Stage 7; generation should produce valid links by construction.

### 3. repair_and_assert_lane_section_successors() — **MOVE_TO_SOURCE_STAGE**
**Location**: `stage_08_integrity.py:592-601`, imported from `quality/check_lane_section_successors.py`
**Mutation**: Repairs intra-road laneSection successor discontinuities (adds `<successor>` within same road's lane sections).
**Impact**: Fixes lane continuity within a road.
**Action**: This is a SOURCE-STAGE repair (intra-road topology). Should run in Stage 7 after lane topology is finalized.

### 4. autofix_missing_lane_successors() — **MOVE_TO_SOURCE_STAGE**
**Location**: `stage_08_integrity.py:722-726`, `fixes/fix_missing_lane_successors.py`
**Mutation**: Infers and adds missing lane-level `<successor>` elements from road/junction topology.
**Impact**: Adds lane successors that were missing after Stage 7.
**Action**: **This IS the GAP-048 fix**. Must run in Stage 7 (source stage), not Stage 8. The GAP-048 implementation already does this in Stage 7 via `lane_successor_topology.py`.

### 5. downgrade_broken_driving_lanes_to_none() — **DELETE_OBSOLETE**
**Location**: `stage_08_integrity.py:769-776`, `quality/check_lane_connectivity.py`
**Mutation**: Changes `type="driving"` to `type="none"` for lanes without successors.
**Impact**: Masks topology defects by removing lanes from CARLA's drivable network.
**Action**: **DELETE**. This is a cosmetic workaround that hides defects. Not acceptable for thesis evidence.

### 6. Remove driving lanes with id="0" — **MOVE_TO_SOURCE_STAGE**
**Location**: `stage_08_integrity.py:532-537`
**Mutation**: Removes lane elements with illegal `id="0"`.
**Action**: Move to Stage 7 (or earlier OSM→XODR conversion) where lane IDs are assigned.

### 7. Add missing `<link>` elements — **MOVE_TO_SOURCE_STAGE**
**Location**: `stage_08_integrity.py:542-550`
**Mutation**: Adds empty `<link>` elements to driving lanes that lack them.
**Action**: Move to Stage 7 where lane topology is constructed.

---

## M3 Regression Cases (Three Specific Lanes)

From GAP-048 report:
> M3 proved: three invalid lane successors are absent BEFORE and absent after Stage 7, but present after Stage-8 simulated repair.

The three cases from GAP048_STAGE8_SIMULATION.json:
1. **Road 49289, Lane -2**
2. **Road 51702, Lane 2**
3. **Road 51702, Lane 1**

These lanes were valid after Stage 7 (GAP-048 fix applied) but became invalid after Stage 8 mutation (likely `LaneLinkBuilder.regenerate()` or `sanitize_junction_lane_links()` overwriting the Stage 7 repairs).

---

## Required Action

**STAGE8_LANELINK_MUTATION_ALLOWED = false**

All lane topology mutations must be moved to Stage 7 (source stage):
1. LaneLink generation → Stage 7 (part of junction topology creation)
2. LaneLink validation → Stage 7 (post-generation check)
3. Intra-road laneSection successor repair → Stage 7
4. Missing lane successor inference (GAP-048 fix) → Stage 7 (already implemented in `lane_successor_topology.py`)
5. Remove id=0 lanes → Stage 7 or earlier
6. Add missing `<link>` elements → Stage 7

Stage 8 must become **PURE_VALIDATION_ONLY**:
- Verify topology integrity
- Run geometric continuity gates
- Run visual smoke gates
- Run schema/uniqueness checks
- **NEVER** add/change/prune lane predecessor/successor IDs

---

## Regression Test Requirement

Add test using the exact three M3 cases:
```python
def test_stage8_no_lane_topology_mutation():
    """Verify Stage 8 does not mutate lane predecessor/successor IDs."""
    # Load Stage 7 output with GAP-048 fixes applied
    # Run Stage 8 validation only
    # Assert the three M3 lanes still have valid successors
    # Assert no new invalid targets introduced
```

**Required**: `INVALID_TARGETS_AFTER = 0`