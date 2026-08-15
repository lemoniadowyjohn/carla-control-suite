# E1B Loadability Connector Repair

Verdict: `E1B_LOADABILITY_CONNECTOR_REPAIR_PASS`

## Candidate

- Input: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_elevated_safe.xodr`
- Input sha256: `7709d5c949f3cf05a1aebc17d5a974816b9f5c5f8be4405e3b254b62c6a16d61`
- Reference: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_final_repaired.xodr`
- Reference sha256: `6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02`
- Output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_elevated_safe_loadable.xodr`
- Output sha256: `90f1e4f7b7bc1876c7a29fa4ac862b218531fb367d0be73b91920f9411ad8982`

## Repair

- Rule: for a target zero-length connector geometry, copy the positive geometry length from the same road id and geometry index in the flat crash-safe reference, only when road length and geometry s/x/y/hdg match.
- Geometry lengths changed: `12`
- Repair skips: `0`

## Counts

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| roads | 32710 | 32710 | 0 |
| junctions | 3646 | 3646 | 0 |
| signals | 3467 | 3467 | 0 |
| objects | 66 | 66 | 0 |
| crosswalk_objects | 66 | 66 | 0 |
| elevation_segments | 418243 | 418243 | 0 |
| nonzero_elevation_segments | 418243 | 418243 | 0 |
| roads_with_elevation_profile | 32710 | 32710 | 0 |

## Diagnostics

- Nonpositive geometries: `12 -> 0`
- G19 violations: `0 -> 0`

## Loadability Preflight

- Status: `ok`
- Errors: `0`
- Warnings: `81072`
- Warning class `carla_compat_gate:missing_offset`: `1`
- Warning class `strict_validator:elev_jump`: `780`
- Warning class `strict_validator:geom_xy_large`: `80261`
- Warning class `strict_validator:road_length_mismatch`: `30`

## Acceptance Checks

- `all_nonpositive_geometries_repaired`: `True`
- `all_preexisting_nonpositive_geometries_touched`: `True`
- `crosswalk_objects_preserved`: `True`
- `elevation_segments_preserved`: `True`
- `g19_clean_after`: `True`
- `g19_clean_before`: `True`
- `junctions_preserved`: `True`
- `no_reference_repair_skips`: `True`
- `nonzero_elevation_preserved`: `True`
- `objects_preserved`: `True`
- `preflight_error_count_zero`: `True`
- `roads_preserved`: `True`
- `roads_with_elevation_profile_preserved`: `True`
- `signals_preserved`: `True`

## Scope

- Candidate production only.
- No certifier or gate logic changed.
- No CARLA/live run performed.
- ESCALATE_TO_CLAUDE before certification use.
