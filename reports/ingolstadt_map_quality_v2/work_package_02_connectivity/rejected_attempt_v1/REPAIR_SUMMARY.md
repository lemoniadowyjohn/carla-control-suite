# WP2B V1 Connectivity Repair — Rejection Summary

## Verdict

**CONNECTIVITY_REPAIR_REJECTED**

Campaign-level verdict: **COORDINATE_VERIFIED_CONNECTIVITY_REJECTED**

## Candidate

| Field | Value |
|-------|-------|
| File | `candidate_connectivity_repaired.xodr` |
| Byte SHA-256 | `c3dc29d3f570d929cbe664961446ea76fd3b8c74b0f4668ade99a67995a7ca43` |
| File size | 89,206,190 bytes |
| Producer commit | `877e9aef` (baseline) |
| Rejected by commit | `bfde9494` (P15) |

## Repair Algorithm

The V1 repair algorithm operated on the coordinate-corrected candidate and attempted to repair missing predecessor/successor links in the road network. The algorithm proposed:

- 4,596 predecessor repairs — **0 accepted**
- 7,463 successor repairs proposed — **7,144 accepted** by the repair script itself

## Independent Verification (WP2C) Results

| Metric | Threshold | Observed | Result |
|--------|-----------|----------|--------|
| successors_repaired | — | 7,144 | — |
| successors_rejected_by_independent_validation | — | 6,132 | **FAIL** |
| predecessor_repairs_accepted | >0 | 0 | **FAIL** |
| directionally_wrong_reciprocals_introduced | 0 | 10,098 | **FAIL** |
| references_to_missing_junction_ids | 0 | 656 | **FAIL** |
| geometry_mutation | 0 | 0 bytes | PASS |
| lane_mutation | 0 | 0 lanes changed | PASS |
| road_deletion | 0 | 0 roads deleted | PASS |

## Why Rejected

1. **Distance/heading validation missing**: The repair script accepted 7,144 successor links without checking geometric validity (distance ≤ 15m, heading diff ≤ 15°). WP2C independent validation rejected 6,132 (86%) of these as invalid.

2. **Predecessor repair asymmetry**: The repair script proposed 4,596 predecessor repairs but accepted 0 — the predecessor validation logic is defective (overly strict or checking the wrong geometric relationship).

3. **Directional reciprocity violations**: Successor-only repairs created 10,098 links that cannot be reciprocated correctly, violating OpenDRIVE reciprocity semantics.

4. **Pre-existing junction defects**: 656 junction connections reference missing junction IDs — a baseline defect not addressed by the repair.

## Key Evidence

- `verification/00_WP2C_EXECUTIVE_STATUS.md` — executive-level verdict
- `verification/15_WP2C_VERDICT.md` — detailed gate results
- `verification/04_REJECTED_REPAIRS.csv` — 6,132 individually rejected repairs
- `verification/06_RECIPROCITY_MATRIX_RESULTS.json` — reciprocity analysis
- `verification/13_HASH_REGISTRY.json` — hash evidence (candidate matches reported)
- `promotion_block.json` — explicit promotion block marker

## Decision

This candidate **must not** be promoted to any downstream stage. The repair algorithm must be fixed to:
1. Apply distance ≤ 15m and heading diff ≤ 15° validation before accepting repairs
2. Fix predecessor repair logic to match successor acceptance criteria
3. Ensure every successor A→B has a corresponding predecessor B←A

See `REJECTION_RECORD.json` for machine-readable rejection details.
