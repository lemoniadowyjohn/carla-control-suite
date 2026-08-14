# E1 Elevation Merge

Verdict: `ELEVATED_SAFE_CANDIDATE_PRODUCED`

## Candidate

- Output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_elevated_safe.xodr`
- Output sha256: `7709d5c949f3cf05a1aebc17d5a974816b9f5c5f8be4405e3b254b62c6a16d61`
- Elevated parent: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T050000Z\candidate_h_signal_enrichment.xodr`
- Elevated parent sha256: `8050ade947111513af7fb4042a41b788b12fbee876d150e1c75f7113bfff7cd7`
- Crash-safe reference: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\campaigns\ingolstadt_cooked_perception_v1\candidate\ingolstadt_perception_final_repaired.xodr`
- Crash-safe reference sha256: `6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02`

## Repair Source

- Lineage: `reports/post_audit_hardening/20260811T000000Z_C3_PROTOCOL, reports/post_audit_hardening/20260813T000000Z_C3_REGOVERN`
- Runtime rule reused: `ultimate_pipeline/core/carla_opendrive_loader.py::repair_road_lengths`
- Rule: `if max(planView.geometry.s + geometry.length) > road.length, set road.length = repr(geom_end + 1e-3)`

## Counts

| Metric | Elevated parent | Output | Delta |
| --- | ---: | ---: | ---: |
| roads | 32710 | 32710 | 0 |
| junctions | 3646 | 3646 | 0 |
| signals | 3467 | 3467 | 0 |
| signal_references | 0 | 0 | 0 |
| objects | 0 | 66 | 66 |
| crosswalk_objects | 0 | 66 | 66 |
| elevation_segments | 418243 | 418243 | 0 |
| nonzero_elevation_segments | 418243 | 418243 | 0 |
| roads_with_elevation_profile | 32710 | 32710 | 0 |

## G19 Length Invariant

| Candidate | Violations | Roads checked | Max excess m |
| --- | ---: | ---: | ---: |
| Elevated parent | 767 | 32710 | 1.00001216197e-08 |
| Crash-safe reference | 0 | 32710 | 0 |
| Output | 0 | 32710 | 0 |

## Touch Scope

- Road length attributes changed: `767`
- Preexisting violating road keys: `767`
- Unexpected non-violating length changes: `0`
- Full violating road IDs and overflow values are in `E1_ELEVATION_MERGE.json` under `before.g19.violation_details`.

## Object Carry

- Source road objects: `66`
- Objects merged: `66`
- Duplicate objects skipped: `0`
- Feasible: `True`

## Loadability Preflight

- `preflight_xodr_loadability` status: `fail`
- Preflight errors: `24`
- Preflight warnings: `81072`
- Error class `carla_compat_gate:geometry_length_invalid`: `12`
- Error class `strict_validator:geom_len_nonpositive`: `12`
- Phase H loadability verdict: `H_LOADABILITY_MATCHES_G0_BASELINE`
- Phase H candidate errors: `24`
- G0 baseline errors: `24`
- New/exceeded error classes: `{}`

## Offline Validation

- XML parse: `ok`
- `check_xodr_schema` uniqueness issues: `0`
- `check_carla_import_s` issues: `0`
- `xodr_strict_validator` errors: `12`

## Acceptance Checks

- `all_preexisting_violations_repaired`: `True`
- `all_source_objects_carried`: `True`
- `carla_import_s_clean`: `True`
- `elevation_segments_preserved`: `True`
- `expected_junction_count`: `True`
- `expected_road_count`: `True`
- `g19_violations_removed`: `True`
- `junctions_preserved`: `True`
- `min_nonzero_elevation_segments`: `True`
- `min_signal_count`: `True`
- `nonzero_elevation_preserved`: `True`
- `object_merge_feasible`: `True`
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
- ESCALATE_TO_CLAUDE before this candidate is used for certification.
