# DSV02 — OSM→XODR Generator & Structural-Validation Donor Discovery

**Assigned model:** DeepSeek V4 Light · **Difficulty:** 3/10 · **Mode:** READ-ONLY
**Coordinator:** Claude Opus 4.8 · **Parent campaign:** `ingolstadt_cooked_perception_v1`
**Prereq:** R00 satisfied. Runs in PARALLEL with DSV01.

## Hard rules
- Read-only. Do NOT run XODR generation, OSM2World, Blender, Unreal, or CARLA.
- Content hashes over filenames (rule 4.4). No global-merge recommendation.
- `run_11` XODR is **historical evidence only** — the user reports unresolved defects; do NOT declare it the new base.

## Search scope
Same 10 worktrees as DSV01 (see R00_worktrees.md §2). Pay special attention to:
`carla_rr_recovery` (RoadRunner recovery; DS05 XODR inventory came from this family),
`carla_main_governed/work/codex-full-pipeline-rerun-20260427` (full OSM→XODR rerun),
`carla_main_governed_worktrees/codex-jsnap-20260428` (junction connector snap).

## Find
`Osm2Odr`, `osm_to_xodr`, `osm_to_xodr_wrapper`, `ConverterProfile`, `main_pipeline`, `ultimate_pipeline.cli`,
raw XODR outputs, candidate XODR outputs, run manifests, **input OSM hashes**, conversion settings,
CARLA/Osm2Odr version, projection settings, `<geoReference>`, `<offset>`.

## Per OSM→XODR implementation, record
worktree · branch · SHA · entry point · active caller · input OSM · **input OSM sha256** · bbox ·
converter settings · lane-width policy · traffic-light policy · projection · output · **output sha256** ·
tests · known failures.

## XODR artifact inventory
Identify ALL generated XODR newer than `run_11` — **but do NOT declare any authoritative.** For each, read-only structural summary ONLY (no mutation):
roads · junctions · connections · LaneLinks · primitive counts · signals · elevation records ·
invalid references · nonfinite values · road-link coverage.

## Preservation check (read-only)
Confirm exact location + sha256 of the protected artifacts (do NOT modify):
`thesis_results/structural_gap_v1/run_11/`, `artifacts/final_runs/scenario_b_audit/contract_run/`,
`08_final_structural_gap.xodr`, `submission/results/structural_gap_run11/auto_aligned_rigid.xodr`.

## Best-donor identification (SEPARATE per subsystem)
OSM validation · OSM→XODR conversion · canonical geometry · topology validation · lane validation ·
elevation validation · artifact transactions · CARLA standalone loading.

## Required outputs
- `reports/visual_structural_reconciliation/DSV02_xodr_donor_matrix.md`
- `reports/visual_structural_reconciliation/DSV02_xodr_donor_matrix.json`

## Verdict line
End with one of: `XODR_DONORS_MAPPED` · `XODR_CANDIDATES_FOUND_UNVERIFIED` · `NO_TRUSTWORTHY_XODR_SOURCE`.
Return control to the Claude coordinator.
