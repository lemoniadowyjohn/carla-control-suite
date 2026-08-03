# G7 — roadMark semantics

- run_id: `20260804T030000Z`
- verdict: **PHASE_G_ROADMARK_SEMANTICS_PASS**
- input: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T020000Z\candidate_g6_junction_lanelinks.xodr`
- output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T030000Z\candidate_g7_roadmarks.xodr`

## Audit (input)

- invalid_type: 0
- invalid_weight: 0
- invalid_color: 0
- invalid_lanechange: 0
- missing_roadmark: 0
- visible_zero_width: 4894
- visible_neg_width: 0
- solid_crossing_allowed: 0
- solid_lanechange_missing: 17024
- advisory_none_with_width: 9941

## Repair

- widths fixed (visible marking with width 0.00 -> 0.13): 4894
- laneChange added (solid -> none): 17024

## Identity

- lane-topology hash before: `3547b06a2acd3106952b296fc16e266b9afc65b70a58bc3a6ed3bef02aff12b0`
- lane-topology hash after: `3e60c78820ffc4fc1b929ae995b65e4f0540ba6d0962b62759560eb344837827`

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

## Fixtures

- clean: PASS (defects {'invalid_type': 0, 'invalid_weight': 0, 'invalid_color': 0, 'invalid_lanechange': 0, 'missing_roadmark': 0, 'visible_zero_width': 0, 'visible_neg_width': 0, 'solid_crossing_allowed': 0, 'solid_lanechange_missing': 0})
- zero_width_solid: PASS (defects {'invalid_type': 0, 'invalid_weight': 0, 'invalid_color': 0, 'invalid_lanechange': 0, 'missing_roadmark': 0, 'visible_zero_width': 1, 'visible_neg_width': 0, 'solid_crossing_allowed': 0, 'solid_lanechange_missing': 0})
- solid_no_lanechange: PASS (defects {'invalid_type': 0, 'invalid_weight': 0, 'invalid_color': 0, 'invalid_lanechange': 0, 'missing_roadmark': 0, 'visible_zero_width': 0, 'visible_neg_width': 0, 'solid_crossing_allowed': 0, 'solid_lanechange_missing': 1})
- solid_crossing: PASS (defects {'invalid_type': 0, 'invalid_weight': 0, 'invalid_color': 0, 'invalid_lanechange': 0, 'missing_roadmark': 0, 'visible_zero_width': 0, 'visible_neg_width': 0, 'solid_crossing_allowed': 1, 'solid_lanechange_missing': 0})
- invalid_values: PASS (defects {'invalid_type': 1, 'invalid_weight': 1, 'invalid_color': 1, 'invalid_lanechange': 0, 'missing_roadmark': 0, 'visible_zero_width': 0, 'visible_neg_width': 0, 'solid_crossing_allowed': 0, 'solid_lanechange_missing': 0})

Lane 0 roadMarks are the optional centerline marks (cosmetic in CARLA for zero-width lanes); they are normalised, not removed.  'none' type with positive width is harmless and reported advisory only.