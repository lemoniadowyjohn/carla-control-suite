# G6 — junction LaneLink validation and repair

- run_id: `20260804T020000Z`
- verdict: **PHASE_G_JUNCTION_LANELINKS_PASS**
- input: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T000000Z\candidate_g5_lane_types.xodr`
- output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T020000Z\candidate_g6_junction_lanelinks.xodr`

## Metrics (input -> output)

| metric | input | output |
|---|---|---|
| connections audited | 22816 | 22816 |
| laneLinks audited | 32040 | 32156 |
| missing from-lanes | 0 | 0 |
| missing to-lanes | 0 | 0 |
| duplicate from-lanes | 0 | 0 |
| driving from-coverage gaps | 125 | 0 |
| driving to-coverage gaps | 0 | 0 |
| type-incompatible laneLinks | 0 | 0 |
| link-consistency advisory | 0 | 0 |

## Repair

- laneLinks added: 116
- repair issues: 0

## Checks (output)

- no_missing_from_lanes: PASS
- no_missing_to_lanes: PASS
- no_duplicate_from_lanes: PASS
- complete_driving_from_coverage: PASS
- complete_driving_to_coverage: PASS
- no_type_incompatible_lanelinks: PASS

## Fixtures

- clean_4way: PASS (defects {'missing_from_lanes': 0, 'missing_to_lanes': 0, 'duplicate_from_lanes': 0, 'missing_driving_from_coverage': 0, 'missing_driving_to_coverage': 0, 'type_incompatible_lanelinks': 0})
- missing_to: PASS (defects {'missing_from_lanes': 0, 'missing_to_lanes': 1, 'duplicate_from_lanes': 0, 'missing_driving_from_coverage': 1, 'missing_driving_to_coverage': 2, 'type_incompatible_lanelinks': 0})
- missing_from: PASS (defects {'missing_from_lanes': 1, 'missing_to_lanes': 0, 'duplicate_from_lanes': 0, 'missing_driving_from_coverage': 2, 'missing_driving_to_coverage': 1, 'type_incompatible_lanelinks': 0})
- missing_coverage: PASS (defects {'missing_from_lanes': 0, 'missing_to_lanes': 0, 'duplicate_from_lanes': 0, 'missing_driving_from_coverage': 1, 'missing_driving_to_coverage': 1, 'type_incompatible_lanelinks': 0})
- roundabout_approach: PASS (defects {'missing_from_lanes': 0, 'missing_to_lanes': 0, 'duplicate_from_lanes': 0, 'missing_driving_from_coverage': 0, 'missing_driving_to_coverage': 0, 'type_incompatible_lanelinks': 0})

## Identity

- lane-topology hash before: `3547b06a2acd3106952b296fc16e266b9afc65b70a58bc3a6ed3bef02aff12b0`
- lane-topology hash after: `efa5fe2f503a6faa02799680c5369f4b09c845f2157868c88eae1cec7d4487fc`

| protected domain | matches G0 |
|---|---|
| planview_hash | PASS |
| road_length_hash | PASS |
| elevation_profile_hash | PASS |
| road_link_hash | PASS |
| junction_structure_hash | PASS |
| connector_geometry_hash | PASS |
| contactpoint_hash | PASS |

- G4 lane continuity still passes: PASS

from/to lanes are resolved against the contacted sections (incoming road end at this junction; connecting road start/end by contactPoint). Uncovered driving lanes converge onto the driving target of their routed neighbour (inner preferred, outer fallback); each repair adds the junction laneLink plus the mirror lane link on the connecting road's lane at the junction end.  Advisory consistency items compare the connecting road's own lane links with the junction LaneLinks.