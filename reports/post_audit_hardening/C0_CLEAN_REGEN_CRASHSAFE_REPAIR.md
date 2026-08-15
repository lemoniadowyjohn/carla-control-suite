# C0 Clean Regen Crash-Safe Repair

Verdict: `ELEVATED_SAFE_CANDIDATE_PRODUCED`

## Candidate

- Output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_clean_regen_crashsafe_20260815.xodr`
- Output sha256: `83418373f1996c6707293c5571b2798f9cf7c06a5b243e8d049848efdc73080e`
- Elevated parent: `C:\tmp\c0_clean_regen_offline_lanes_20260815\pipeline_out\C0_CLEAN_REGEN_OFFLINE_LANES\08_final_C0_CLEAN_REGEN_OFFLINE_LANES_laneSectionFixed_lane_successor_fixed.xodr`
- Elevated parent sha256: `53bcf5ec5281bb7a1427d841f021e79e9f7865ee959f67a252491f81e3799b7a`

## Repair Source

- Lineage: `reports/post_audit_hardening/20260811T000000Z_C3_PROTOCOL, reports/post_audit_hardening/20260813T000000Z_C3_REGOVERN`
- Runtime rule reused: `ultimate_pipeline/core/carla_opendrive_loader.py::repair_road_lengths`
- Rule: `if max(planView.geometry.s + geometry.length) > road.length, set road.length = repr(geom_end + 1e-3)`

## Counts

| Metric | Elevated parent | Output | Delta |
| --- | ---: | ---: | ---: |
| roads | 32297 | 32297 | 0 |
| junctions | 3568 | 3568 | 0 |
| signals | 0 | 0 | 0 |
| signal_references | 0 | 0 | 0 |
| objects | 46112 | 46112 | 0 |
| crosswalk_objects | 0 | 0 | 0 |
| elevation_segments | 32297 | 32297 | 0 |
| nonzero_elevation_segments | 32297 | 32297 | 0 |
| roads_with_elevation_profile | 32297 | 32297 | 0 |

## G19 Length Invariant

| Candidate | Violations | Roads checked | Max excess m |
| --- | ---: | ---: | ---: |
| Elevated parent | 867 | 32297 | 1.00001216197e-08 |
| Output | 0 | 32297 | 0 |

## Touch Scope

- Road length attributes changed: `867`
- Preexisting violating road keys: `867`
- Unexpected non-violating length changes: `0`
- Full violating road IDs and overflow values are in `C0_CLEAN_REGEN_CRASHSAFE_REPAIR.json` under `before.g19.violation_details`.

## Offline Validation

- XML parse: `ok`
- `check_xodr_schema` uniqueness issues: `0`
- `check_carla_import_s` issues: `0`
- `xodr_strict_validator` errors: `0`

## Acceptance Checks

- `all_preexisting_violations_repaired`: `True`
- `carla_import_s_clean`: `True`
- `elevation_segments_preserved`: `True`
- `expected_junction_count`: `True`
- `expected_road_count`: `True`
- `g19_violations_removed`: `True`
- `junctions_preserved`: `True`
- `min_nonzero_elevation_segments`: `True`
- `nonzero_elevation_preserved`: `True`
- `only_preexisting_violating_road_lengths_changed`: `True`
- `roads_preserved`: `True`
- `roads_with_elevation_profile_preserved`: `True`
- `schema_ok_or_skipped`: `True`
- `signal_references_preserved`: `True`
- `signals_preserved`: `True`
- `xml_parse_ok`: `True`
- `xml_uniqueness_clean`: `True`

## Scope

- This is candidate production evidence only.
- No certifier or gate logic was changed.
- No CARLA/live certification run was performed.
- This report only covers the G19 crash-safe length repair. It does not pin the C0 auto map of record.
- ESCALATE_TO_CLAUDE before this candidate is used for certification.
