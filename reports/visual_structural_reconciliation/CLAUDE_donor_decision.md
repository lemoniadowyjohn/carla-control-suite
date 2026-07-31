# CLAUDE Donor Decision

Report: `CLAUDE_donor_decision`
Task: `C55V01A`
Date: 2026-07-31
Repository: `carla-control-suite.git`
Branch: `integration/governed-map-quality-20260729`
Execution base SHA: `f94b2195a30d6dddac6208adfada6f5a4c94a89f`
P4-approved base ancestor: `a7919117c245ecd7e0c47ff541e4b4d6151fd8e0`

## Governance Boundary

This decision is metadata and candidate-artifact preparation only. Real map mutation remains `NO`.

Protected paths are not to be overwritten, renamed, deleted, or mutated:

- `thesis_results/structural_gap_v1/run_11/`
- `08_final_structural_gap.xodr`
- `scenario_b_audit/contract_run/`
- `submission/results/structural_gap_run11/`

## Approved Donors

| Subsystem | Decision | Donor | Donor SHA | Use |
|---|---|---|---|---|
| OSM to XODR generator | `USE_AS_REFERENCE` | `carla_main_governed/work/codex-full-pipeline-rerun-20260427` | `6b2506210a23637eb15f8773674de3ab560f0e6d` | Use the reviewed conversion path for deterministic candidate regeneration. No whole-worktree merge. |
| Visual OSM2World to Blender to FBX | `USE_AS_REFERENCE` | `carla_main_governed` | `deb261bf3bd21c2c7b399cbd69434fb8aade5086` | Prefer source-matched regeneration from the same OSM. If unavailable, ratify `CARLA_GENERATED_ROAD` fallback. |
| Junction snap | `USE_AS_REFERENCE` | current base history | `0578e45bfe79452879372a9ab095e660e8a94e63` | Reuse only because it is already on the base. Do not re-import or run structural mutation. |
| Candidate artifacts | `REGENERATE_ARTIFACT` | C55V01a campaign namespace | `f94b2195a30d6dddac6208adfada6f5a4c94a89f` | Generate isolated candidates under `campaigns/ingolstadt_cooked_perception_v1/`. |

## Source Evidence

- `reports/visual_structural_reconciliation/DSV01_visual_donor_matrix.*`
- `reports/visual_structural_reconciliation/DSV02_xodr_donor_matrix.*`
- `reports/visual_structural_reconciliation/C44V01_coordinate_contract.*`
- `reports/visual_structural_reconciliation/C44V01_alignment_results.json`
- `reports/architecture_gate/AG07_verdict.*`

## Verdict

`DONORS_FIXED_FOR_C55V01A_METADATA_ONLY`
