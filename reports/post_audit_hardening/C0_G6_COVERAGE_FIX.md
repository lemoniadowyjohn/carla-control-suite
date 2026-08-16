# C0 G6 Coverage Fix

Date: 2026-08-16

Verdict: C0_G6_COVERAGE_UNBLOCKED_OFFLINE

## Scope

This pass fixes the remaining G6 coverage blocker left after `C0_BLOCKER_FIXES.md`. It changes the G6 junction-lane coverage checker and repair logic only; it does not mutate or commit a map artifact and does not run CARLA.

## Root Cause

The remaining five `missing_driving_from_coverage` records were not all real missing routes:

| Class | Evidence | Fix |
| --- | --- | --- |
| Iterative repair miss | Roads `47310` and `47309` had lane `-1` unresolved because lane `-2` needed to be repaired first. A single-pass repair stopped too early. | `repair_coverage_gaps` now iterates until no more safe neighbour-merge repairs are possible. |
| Directionality false positive | Road `46620` lane `+1` was checked as incoming at the road end. In the generated right-hand traffic maps, positive lanes travel toward the road start, not into the road end. | G6 coverage is now endpoint-direction aware. |
| Inflated residual count | Coverage dedupe used `locals()[key] = uniq`, which is not reliable for function-local variables. | Coverage lists now dedupe through explicit assignments. |

## Full-Map Probe

Probe input: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_clean_regen_crashsafe_20260815.xodr`

Repair sequence used for the probe:

1. `repair_and_assert_lane_section_successors`
2. `repair_coverage_gaps`
3. `audit_junction_lanelinks`

Result:

| Metric | Before this fix | After this fix |
| --- | ---: | ---: |
| `missing_driving_from_coverage` | 5 | 0 |
| `missing_driving_to_coverage` | 0 | 0 |
| `missing_from_lanes` | 0 | 0 |
| `missing_to_lanes` | 0 | 0 |
| `duplicate_from_lanes` | 0 | 0 |
| `type_incompatible_lanelinks` | 0 | 0 |
| `lane_link_consistency_advisory` | 0 | 0 |
| repair issues | 3 unique | 0 |

The fixed probe added 126 laneLinks and all G6 checks passed.

## Tests

New unit coverage locks:

- opposite-direction positive lanes at a road end are not required as incoming `from` coverage;
- positive lanes at a road start are still required;
- opposite-direction positive lanes at a connecting-road start are not required as outgoing `to` coverage;
- chained lane merges repair iteratively across multiple passes.

Internal G6 fixtures:

```text
fixtures_ok: true
```

Targeted offline tests:

```text
45 passed, 4 warnings
```

Full offline suite:

```text
767 passed, 49 warnings in 166.02s (0:02:46)
```

## Boundary

This is still offline evidence. The map is not pinned as drivable until a fresh C0 run emits the candidate, acceptance evidence is regenerated from that exact artifact, and live CARLA load/drivability is tested.
