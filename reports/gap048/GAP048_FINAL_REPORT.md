# GAP-048 Final Report - Road → Junction → Connecting-Road Lane Successor Topology

## Verdict

**GAP048_PARTIAL_UNRESOLVED_TOPOLOGY**

Unique-proof successor repair closes 10180/10563 (96.4%) of broken road→junction lane
successors. The remaining 376 broken driving lanes cannot be resolved without guessing:
261 are genuine forks (multiple distinct valid laneLink targets) and 115 have no
incoming laneLink from their lane (a laneLink-generation deficiency, out of GAP-048 scope).

## Required fields

| Field | Value |
| --- | --- |
| BASE_SHA | `56c749b4` (tip at implementation start); prior baseline `68868f76` confirmed ancestor (exit 0) |
| FIX_SHA | `56c749b4` + uncommitted working-tree changes (module, test, stage_07 wiring; not committed) |
| BROKEN_BEFORE | 10563 |
| THROUGH_JUNCTION_CANDIDATES | 10563 (100% of broken; road_successor_type=junction) |
| THROUGH_JUNCTION_UNAMBIGUOUS | 10180 |
| REPAIRED_THROUGH_JUNCTION | 10180 |
| UNRESOLVED_AFTER | 383 (261 ambiguous + 115 no-candidate + 7 intermediate); 376 after stage-8 intra-road repair |
| INVALID_TARGETS_AFTER | 0 (lane_link_targets ok, 46812 cross-road links checked, 0 issues) |
| SYNTHETIC_FALLBACK_USED | false |
| GAP026_RESULT | fail (checked 23406 / passed 20482 / failed 2924) — unchanged BEFORE and AFTER |
| GAP048_RESULT | GAP048_PARTIAL_UNRESOLVED_TOPOLOGY |
| TARGETED_TESTS | 34 passed in 2.52s |
| FULL_PYTEST | 7669 passed / 15 skipped / 24 failed (1829s), excluding tests/unit/test_writer_lock_concurrency.py (8 passed standalone, 137s) |
| ONE_PIPELINE_TRIAL_RUN | false (NOT_RUN — deferred; outcome deterministic from direct measurement) |
| FINAL_INTEGRITY_RESULT | NOT_RUN — deterministic FAIL (376 broken; stage-8 simulation confirms assert raises) |
| RQ1_N5_STARTED | false |

## What changed (source-stage only, no final-XODR patch)

- `ultimate_pipeline/enrichment/lane_successor_topology.py` (new): strategy 1 (road→road)
  retained; strategy 3 `ROAD_SUCCESSOR_IS_JUNCTION` added — for a terminal driving lane
  whose road-successor is a junction, writes `<successor>` only when exactly ONE distinct
  validated laneLink target exists. Ambiguous (>=2) and no-candidate lanes are left
  unresolved and reported. Dead strategy-2 branch and `_build_junction_lane_map` removed;
  `_build_incoming_lane_candidates` added.
- `ultimate_pipeline/pipeline_stages/stage_07_lanes.py` (modified): calls
  `infer_lane_successors_from_topology(root)` after `LaneWidthClamp.clamp` and before
  `save_xodr`; writes `lane_successor_topology_report.json`; adds to verification report.
- `tests/unit/test_lane_successor_topology.py` (new): 8-test contract matrix (all pass).
- `ultimate_pipeline/tools/gap048_through_junction_population.py` (new): PHASE-2 classifier.
- `submission/infrastructure/ultimate_pipeline/enrichment/lane_successor_topology.py`:
  mirror synced (sha256 match, 12386 bytes).

## Evidence artifacts

- `reports/gap048/GAP048_THROUGH_JUNCTION_POPULATION.json` — BEFORE classification
  (broken_total=10563, partition_ok=true; funnel 10180/261/115/7; strategy1=0).
- `reports/gap048/lane_successor_topology_report.json` — AFTER module report
  (inferred=10180, junction_repaired=10180, unresolved_ambiguous=261,
  unresolved_no_candidate=115, lanes_without_topology=714 all-lane diagnostic).
- `reports/gap048/07_lanes_GAP048_AFTER.xodr` — AFTER artifact (non-destructive copy).
- `reports/gap048/GAP048_PHASE7_CHECKS.json` — BEFORE/AFTER link-target + connectivity +
  GAP-026.
- `reports/gap048/GAP048_STAGE8_SIMULATION.json` — stage-8 → final_integrity simulation.
- `reports/gap048/GAP048_FULL_PYTEST.txt` — full pytest log.

## Why the remainder is unresolved (not a tolerance issue)

- Ambiguous (261): lane forks to >=2 distinct connecting-road lanes; OpenDRIVE puts
  connectivity in the explicit per-lane laneLink, and multiple targets = genuine fork.
  Choosing one would be guessing (policy violation).
- No-candidate (115): the incoming lane carries no laneLink (generator-laneLink
  deficiency, adjacent to GAP-026 territory) — not a lane-successor mapping problem.
- GAP-048 deliberately does NOT raise any tolerance and does NOT run the forbidden
  Stage-8/final-XODR `fix_missing_lane_successors` patch; that path is disabled
  (settings/env absent), so stage 8 takes the fail-loud branch.

## Provenance

- Working branch: `integration/production-large-map-20260918` (per repo policy).
- HEAD `56c749b4`; prior baseline `68868f76` confirmed ancestor. Changes currently
  uncommitted in the working tree.
- Pin verified upstream by `verify_pinned_map("auto_map_of_record")`.
- BEFORE probe artifact:
  `reports/rq1_trial_runs_x2_verify/run_01/20261008_024449_086823/07_lanes_20261008_024449_086823.xodr`
  sha256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` (map-of-record).

## Unrelated full-suite failures (not GAP-048)

24 failures, 0 in lane/stage code: 23 in `tests/unit/test_blender_geometry_contract.py`
(untracked in-flight blender-geometry contract work) and 1 in
`tests/unit/test_a1_a2_path_and_frame_resolution.py::test_missing_osm2world_fails_precisely`
(env/binary dependent). `tests/unit/test_writer_lock_concurrency.py` stalls only under the
full-suite run (order/contention); passes standalone.
