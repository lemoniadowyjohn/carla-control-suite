# Divergent GAP-048 Module Semantic Diff

**Date**: 2026-10-11
**ef3003c2 version SHA256**: `40900d7cd329a80c2ec7892e0f97954dc72c711a6cdc15a382b9099a8de6a7a0`
**Working tree version SHA256**: `7ee02c0215c05661f89c8e00ef22f29d2882a3eb4f933d5466e0f695eed30e76`
**Submission mirror SHA256**: `7ee02c0215c05661f89c8e00ef22f29d2882a3eb4f933d5466e0f695eed30e76` (matches working tree)

---

## Summary of Semantic Differences

| Aspect | ef3003c2 (Committed) | Working Tree (Divergent) | Impact |
|--------|---------------------|-------------------------|--------|
| **Strategy 1** | ROAD_SUCCESSOR_IS_ROAD | ROAD_SUCCESSOR_IS_ROAD | Same logic |
| **Strategy 2** | Dead code (guarded by unreachable elif) | **REMOVED** | Dead code elimination |
| **Strategy 3** | `resolve_through_junction()` with 7 buckets | `_build_incoming_lane_candidates()` + terminal-section filter | **Major behavioral change** |
| **Candidate validation** | All driving lanes anywhere on connecting road | Only boundary laneSection at contactPoint | **Stricter validation** |
| **Ambiguous handling** | Returns AMBIGUOUS_MULTIPLE_TARGETS bucket | Records as `unresolved_ambiguous` with candidate IDs | Better reporting |
| **No-candidate handling** | Returns NO_MATCHING_LANELINK / TARGET_LANE_MISSING | Records as `unresolved_no_candidate` | Better reporting |
| **Terminal section filter** | Not explicitly enforced | **ENFORCED** (`is_terminal` check) | Prevents mid-road writes |
| **Lane section ordering** | Iterates in XML order | **Sorts by `s` attribute** | Deterministic processing |
| **Report structure** | Simple counters | Detailed unresolved records + counts | Full provenance |

---

## Critical Behavioral Changes

### 1. Strategy 2 Dead Code Removal
**ef3003c2**: Had a dead branch guarded by `elif road_succ[0] != "road"` that then checked `road_succ[0] == "road"` again — unreachable.
**Working tree**: Explicitly removed with comment referencing HH1 verification report.
**Impact**: No functional change (was dead), but cleaner.

### 2. Junction LaneLink Validation Strictness
**ef3003c2**: `_all_driving_lane_ids()` collected **all driving lanes across ALL laneSections** on the connecting road.
**Working tree**: `_get_boundary_lane_section()` + `_get_driving_lane_ids()` validates **only the boundary laneSection** at the connection's `contactPoint`.
**Impact**: **Fewer false positives** — a laneLink target must exist at the correct boundary, not just anywhere on the road.

### 3. Terminal LaneSection Enforcement
**ef3003c2**: Iterated all laneSections, attempted junction resolution on any.
**Working tree**: Only processes junction successor on `is_terminal` (last laneSection by `s` coordinate).
**Impact**: Prevents writing junction-derived successors on non-terminal sections (mid-road), which would be semantically wrong.

### 4. Candidate Enumeration Architecture
**ef3003c2**: `resolve_through_junction(road_id, lane_id)` — single lane query, returns one bucket.
**Working tree**: `_build_incoming_lane_candidates(root, roads)` — **pre-computes ALL candidates** for ALL (incomingRoad, incomingLane) pairs across ALL junctions.
**Impact**: 
- Single pass over junction topology (O(junctions × connections × laneLinks))
- Enables population classification without re-traversal
- Supports GAP048_THROUGH_JUNCTION_POPULATION.json generation

### 5. Unresolved Lane Reporting
**ef3003c2**: Returned bucket string only, no lane identity recorded.
**Working tree**: Records full lane identity (`road_id`, `lane_id`, `junction_id`, `candidate_lane_ids`) for each unresolved case.
**Impact**: Full traceability for GAP-048 population audit.

---

## Population Classification Impact

The working tree version produces the **Phase 2 classifier** output (`GAP048_THROUGH_JUNCTION_POPULATION.json`) that partitioned 10,563 broken lanes into:
- `THROUGH_JUNCTION_UNAMBIGUOUS`: 10,180
- `AMBIGUOUS_MULTIPLE_TARGETS`: 261
- `NO_MATCHING_LANELINK`: 115
- `CONNECTING_ROAD_MISSING` / `TARGET_LANE_MISSING` / others: 7

The ef3003c2 version's `resolve_through_junction` was designed to produce the **same buckets** but:
- Used looser validation (any laneSection on connecting road)
- Did not enforce terminal section
- Did not pre-compute all candidates

The **divergence in reported numbers** (10563/10180/376 vs 10563/???) likely stems from these validation differences.

---

## Provenance Note

The working tree version (sha256 7ee02c02...) was used for:
- `reports/gap048/GAP048_THROUGH_JUNCTION_POPULATION.json`
- `reports/gap048/lane_successor_topology_report.json`
- `reports/gap048/GAP048_FINAL_REPORT.md` (which cites 10180 repaired, 261 ambiguous, 115 no-candidate)

The committed ef3003c2 version (sha256 40900d7c...) was **not** used for these reports — the working tree version was.

The submission/infrastructure mirror was updated to match the working tree version (same hash), suggesting it was synced after the working tree changes.

---

## Recommendation for Convergence

The working tree version is **semantically superior**:
1. Stricter validation (boundary laneSection only)
2. Terminal section enforcement
3. Full candidate pre-computation
4. Complete unresolved provenance

The convergence branch should **adopt the working tree implementation** as the authoritative version, with the following additions from M2.5/M3.5 spec:
- Unanimous lane ID strategy validation (Section 2)
- Adversarial tests (Section 3)
- Stage-8 mutation removal (Section 4)
- Orphan road RCA (Section 5)