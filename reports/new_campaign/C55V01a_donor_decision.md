# C55V01a Donor Decision

Verdict: `DONORS_FIXED_FOR_C55V01A_METADATA_ONLY`

Execution branch: `integration/governed-map-quality-20260729`
Execution base SHA: `f94b2195a30d6dddac6208adfada6f5a4c94a89f`

This stage fixes the donor choices for the metadata-only campaign. It does not authorize real map mutation.

| Subsystem | Decision | SHA |
|---|---|---|
| OSM to XODR generator | `USE_AS_REFERENCE` from `carla_main_governed/work/codex-full-pipeline-rerun-20260427` | `6b2506210a23637eb15f8773674de3ab560f0e6d` |
| Visual pipeline | `USE_AS_REFERENCE` from `carla_main_governed` | `deb261bf3bd21c2c7b399cbd69434fb8aade5086` |
| Junction snap | `USE_AS_REFERENCE`, already on base | `0578e45bfe79452879372a9ab095e660e8a94e63` |
| Campaign candidates | `REGENERATE_ARTIFACT` under campaign namespace | `f94b2195a30d6dddac6208adfada6f5a4c94a89f` |

Protected run and submission artifacts remain immutable.
