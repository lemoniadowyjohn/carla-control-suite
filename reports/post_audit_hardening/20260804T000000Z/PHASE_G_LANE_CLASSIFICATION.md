# G5 — side-lane classification

- run_id: `20260804T000000Z`
- verdict: **PHASE_G_LANE_CLASSIFICATION_PASS**
- input: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260803T160000Z\candidate_f5_bounded_offsets.xodr`
- output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T000000Z\candidate_g5_lane_types.xodr`

## Audit (input)

- restricted lanes: 5
- invalid lane types: 0
- walk-lane-not-outermost: 0
- width-band violations: 0
- multiple walk-side lanes: 0

## Reclassification

- road 44238 lane -1: `restricted` -> `driving`
- road 71769 lane -1: `restricted` -> `driving`
- road 71774 lane -1: `restricted` -> `driving`
- road 71779 lane -1: `restricted` -> `driving`
- road 71784 lane -1: `restricted` -> `driving`

Criteria: width in driving band [2.5, 6.0] m, innermost side lane (|id| == 1), and a driving connection at the same position (explicit lane link, junction connection from a driving incoming road, or road-level link with a driving contacted lane).  Only the `type` attribute changes; geometry is untouched.

## Identity

- lane-topology hash before: `3547b06a2acd3106952b296fc16e266b9afc65b70a58bc3a6ed3bef02aff12b0`
- lane-topology hash after: `3fe9c8429e508fbc18c07c59283a58ce25b1a683551679055426d5c4f6f6e1ea`

| protected domain | matches G0 |
|---|---|
| planview_hash | PASS |
| road_length_hash | PASS |
| elevation_profile_hash | PASS |
| road_link_hash | PASS |
| junction_structure_hash | PASS |
| connector_geometry_hash | PASS |
| contactpoint_hash | PASS |

- G4 type-incompatible lane links after: 0 (was 7)