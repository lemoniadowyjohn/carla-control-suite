# G8 — Phase G acceptance

- run_id: `20260804T040000Z`
- verdict: **PHASE_G_ACCEPTED**
- final candidate: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T030000Z\candidate_g7_roadmarks.xodr`

## Subphase reruns (deterministic, on final candidate)

| subphase | verdict |
|---|---|
| G1 lane inventory | PHASE_G_LANE_INVENTORY_PASS |
| G2 polynomial validation | PHASE_G_POLYNOMIAL_VALIDATION_PASS |
| G3 cross-section | PHASE_G_CROSS_SECTION_PASS |
| G4 lane continuity | PHASE_G_LANE_CONTINUITY_PASS |
| G5 classification defects | {'invalid_lane_types': 0, 'walk_lane_not_outermost': 0, 'width_band_violations': 0, 'multiple_walk_side_lanes': 0, 'restricted_lanes': 0} |
| G6 junction laneLinks | True |
| G7 roadMark defects | {'invalid_type': 0, 'invalid_weight': 0, 'invalid_color': 0, 'invalid_lanechange': 0, 'missing_roadmark': 0, 'visible_zero_width': 0, 'visible_neg_width': 0, 'solid_crossing_allowed': 0, 'solid_lanechange_missing': 0} |

## Identity freeze

- road count: 32710
- lane-topology hash (frozen Phase G baseline): `3e60c78820ffc4fc1b929ae995b65e4f0540ba6d0962b62759560eb344837827`

| protected domain | matches G0 |
|---|---|
| planview_hash | PASS |
| road_length_hash | PASS |
| elevation_profile_hash | PASS |
| road_link_hash | PASS |
| junction_structure_hash | PASS |
| connector_geometry_hash | PASS |
| contactpoint_hash | PASS |

## Loadability preflight

- candidate status: fail (errors 24, warnings 135113)
- G0 baseline status: fail (errors 24, warnings 135113)
- new or exceeded error classes vs baseline: none

Zero-length geometry elements pre-exist in the frozen planView (Phase E/F-approved; planView is protected in Phase G).  Phase G introduces no new loadability errors.

The frozen candidate enters Phase H (CARLA load + drivability) with all Phase G subphase audits green, protected identity hashes identical to the G0 baseline, and the static CARLA compatibility gate passing.