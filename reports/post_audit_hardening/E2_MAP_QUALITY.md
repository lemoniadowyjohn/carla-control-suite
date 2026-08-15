# E2 Map Quality

Verdict: `DRIVABLE_CANDIDATE_PRODUCED`

## Candidate

- Input: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_elevated_safe_loadable.xodr`
- Input sha256: `90f1e4f7b7bc1876c7a29fa4ac862b218531fb367d0be73b91920f9411ad8982`
- Output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_drivable.xodr`
- Output sha256: `352c9003e653027f41ecda5ef11f59a11b07b0ce7294ea1d7d21e4bcc7e63c52`

## Repair Summary

- Header offset: `added_zero_offset_without_moving_geometry`
- Short connector geometry lengths changed: `30`
- Elevation roads smoothed: `405`
- Elevation `a` entries changed: `3130`
- Endpoint-locked residual strict jumps: `3`

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

- G19 violations: `0 -> 0`
- Strict `elev_jump`: `780 -> 4`
- Elevation seam gate: `False -> True`
- Elevation seam steps: `1695 -> 575`
- Elevation continuity issues: `565 -> 574`
- Missing/cliffs gate: `True -> True`
- Elevation structure gate: `True -> True`

## Preflight

- Status: `ok -> ok`
- Errors: `0 -> 0`
- Warnings: `81072 -> 80265`
- After warning class `strict_validator:elev_jump`: `4`
- After warning class `strict_validator:geom_xy_large`: `80261`

## Acceptance Checks

- `crosswalk_objects_preserved`: `True`
- `elevation_missing_and_cliffs_ok`: `True`
- `elevation_seam_gate_ok`: `True`
- `elevation_structure_ok`: `True`
- `g19_clean_after`: `True`
- `g19_clean_before`: `True`
- `junctions_preserved`: `True`
- `nonzero_elevation_preserved`: `True`
- `not_flat`: `True`
- `objects_preserved`: `True`
- `preflight_errors_zero`: `True`
- `roads_preserved`: `True`
- `signals_preserved`: `True`
- `strict_elev_jumps_materially_reduced`: `True`

## Scope

- Candidate production only.
- No certifier/gate logic changed.
- No CARLA/live run performed.
- ESCALATE_TO_CLAUDE before certification use.
