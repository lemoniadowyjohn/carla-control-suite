# Codex — PROMPT CC: validate roundabout-reconstruction-v2 against the real pinned map

## Context

`feature/roundabout-reconstruction-v2-20260907` (real, self-contained, now merged into
`integration/session-batch1-20260912`) added `ultimate_pipeline/topology/roundabout_v2/` -- a
deterministic roundabout detection + reconstruction module (`core.py::detect_candidates()`,
`RoundaboutV2Reconstructor` in `reconstructor.py`, `validator.py`, `lane_provenance_report()` in
`reporting.py`). Its own test suite passes (verified this session, in the merged branch), and an
earlier independent inventory of this branch flagged it as: "Offline tests pass, but full
integration incomplete due to sparse checkout (large pinned maps not materialized); V2 not
integrated into release pipeline." That gap was never closed. This map (Ingolstadt) has real
roundabouts -- this module has never been run against it.

There is currently NO wired CLI/pipeline entry point for this module (confirmed by grep -- no
`main()`, no `if __name__`, no pipeline_stages/ call site). `tests/unit/test_roundabout_v2_regression.py`
imports `Anchor`, `build_junction_lane_links`, `build_segment_roads`, `lane_provenance_report` directly
from the package, giving you the real, current call pattern to build a driver from -- read that test
file first rather than guessing the intended usage.

## PROMPT CC

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912
(has roundabout_v2 already merged -- use it as your starting point, not
fix/post-audit-phase-e-junctions-roundabouts-20260803). Isolated branch:
feature/roundabout-v2-real-map-validation-v1-<date>.

TASK 1: read tests/unit/test_roundabout_v2_regression.py and ultimate_pipeline/topology/roundabout_v2/
in full to understand the real, intended call sequence (detect_candidates -> reconstruct ->
validate_model, or whatever the actual chain is -- verify from the code, do not assume). Write a
standalone driver script (does not need to be a permanent CLI, a scratch/test-only script is fine if
you make its existence and purpose clear in your evidence) that runs this chain against a COPY of the
real pinned map-of-record
(campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr).
Never mutate the actual pinned file -- work on a copy.

TASK 2: report real numbers, not aggregates you can't back up: how many roundabout candidates does
detect_candidates() find on the real map, how many does RoundaboutV2Reconstructor successfully
reconstruct vs. reject/skip (with reasons), and what does validate_model()/validate_segmented_ring()
say about the results. If ANY step throws, crashes, or behaves unexpectedly on real data (as opposed
to the synthetic fixtures its own test suite uses), report that honestly as a finding, not as
something to silently work around.

TASK 3: for any successfully-reconstructed roundabout, run this session's established before/after
methodology: measure_candidate_acceptance.py on the original map vs. the roundabout_v2-modified copy,
and report the delta on every metric (not just roundabout-specific ones) -- confirm nothing else in
the acceptance report regresses. If scripts/measure_candidate_acceptance.py doesn't accept a
roundabout_v2 output directly (e.g. path/schema mismatch), say so and describe exactly what you did
instead.

TASK 4: investigate wiring into the live pipeline, advisory-first, matching this session's established
pattern for exactly this kind of decision (see UP_ENABLE_JUNCTION_CONNECTOR_SNAP and
UP_ENABLE_G6_LANE_COVERAGE_REPAIR in stage_05_geometry.py / stage_08_hygiene.py for the convention:
env-var gated, default off, transactional where the underlying repair mutates geometry, a persisted
JSON report, never a hard pipeline-fail on its own). If Task 2's real-data results are clean and
Task 3 shows no regressions, wire it this way. If Task 2 surfaces real problems (crashes, incorrect
reconstructions, or anything that would make wiring premature), do NOT wire it -- stop and report
exactly what's broken instead, the same way this session declined to wire
UP_ENABLE_ROAD_LINK_TARGET_REPAIR after finding it more invasive/undertested than assumed.

TASK 5: run the full offline test suite. Do not promote anything to auto_map_of_record.

End with:
TASK_1_DRIVER_BUILT: PASS | FAIL -- <call sequence used>
TASK_2_REAL_MAP_RESULTS: <candidates_found> / <reconstructed> / <rejected, with reasons>
TASK_3_ACCEPTANCE_DELTA: <full metric diff, or "not reached" if Task 2 found no reconstructable candidates>
TASK_4_WIRING_DECISION: WIRED (advisory, default off) | NOT_WIRED (with the specific reason)
TASK_5_FULL_OFFLINE_TESTS: PASS | FAIL
MAP_OF_RECORD_MUTATED: NO
```
