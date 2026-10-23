# Merge dependency DAG & simulation matrix — 2026-10-11

**READ-ONLY.** Nothing was merged, rebased, cherry-picked or deleted.
`anything_merged: false`.

Target: `integration/consolidate-fixes-20261008` @ `9fa11e1e`
Production: `68868f76` (unchanged)

## Headline: three of the ten candidates are duplicates, not work

| branch | unique | cons-only | merge-tree | verdict |
|---|---|---|---|---|
| fix/topology-convergence-gap026-gap048-20261011 | **5** | 0 | clean | **DIRECT_MERGE** (fast-forward) |
| fix/gap049-poller-delta-only-20261011 | **1** | 0 | clean | **DIRECT_MERGE** (fast-forward) |
| fix/gap048-through-junction-20261009 | 1 | 11 | clean | **NO_MERGE_SUPERSEDED** |
| fix/gap055-ci-windll-platform-guard-20261011 | 2 | 11 | clean | **REVIEW_REQUIRED** |
| rq2-authority | 2 | 40 | clean | CHERRY_PICK_EXACT_COMMIT |
| rq5-readiness | 2 | 40 | clean | CHERRY_PICK_EXACT_COMMIT |
| tools/rq1-stage-profiler-20261008 | 20 | 27 | **conflict** | NO_MERGE_ALREADY_ABSORBED |
| tools/cook-diagnostics-harness-20261008 | 17 | 27 | **conflict** | NO_MERGE_ALREADY_ABSORBED |
| tools/gap017-diagnostic-toolkit-20261008 | 15 | 27 | **conflict** | NO_MERGE_ALREADY_ABSORBED |

## The two findings that change the plan

**1. `fix/gap048-through-junction-20261009` is already inside the topology branch.**
Stable patch-id of `ef3003c2` is `14e0a70b83ea` — **identical** to topology's
`2af80330` ("GAP-048: source-stage through-junction lane successor repair").
Different SHA, same patch. Merging both would replay the same change twice.

**2. `fix/gap055-ci-windll-platform-guard-20261011` is a DIVERGENT TWIN, and a
clean textual merge would hide it.**

| source branch | patch-id | topology | patch-id |
|---|---|---|---|
| `08a55439` platform-guard module-level ctypes.WinDLL | `5bd46579162d` | `19cdb3a2` | `8744673375b1` |
| `bec68678` guard orphan_terminal_witness WinDLL | `22ab20e979bb` | `3c9048be` | `bdc414013d2b` |

Identical subjects, **different patch-ids**. `git merge-tree` reports CLEAN.
A textual-clean result here means only that the files do not collide on context —
it says nothing about whether the two implementations agree. This is exactly the
case where "merge_clean=true" must not be read as "safe", so it is classified
`REVIEW_REQUIRED` rather than merged.

## The three `tools/*` branches conflict *because they are already merged*

`tools/rq1_stage_profiler.py`, `tools/cook_diagnostics/*` and
`ultimate_pipeline/carla_rpc_diagnostics/*` are **already present in
consolidation** (as `7f320c7b`, `9fa11e1e`, `e10839c6`). Their branches still
report 15–20 "unique" commits, but those are the shared 12-commit polluted base
that exists in neither production nor consolidation. Merging any of them
wholesale would drag that base back in. Hence **PATCH_ALREADY_PRESENT**.

## Dependency DAG (derived from content, not name)

```
consolidation 9fa11e1e
   |
   +-- gap049-poller-delta-only (1) ............ leaf, no deps
   |
   +-- topology-convergence (5) ................ contains GAP-048 + GAP-055 + GAP-026
   |        |
   |        +-- [gap048-through-junction: SUPERSEDED, identical patch-id]
   |        +-- [gap055-platform-guard: REVIEW, divergent patch-id]
   |
   +-- rq2-authority (2) ....................... independent (merge-base 7fbd33ff)
   +-- rq5-readiness  (2) ....................... independent (merge-base 7fbd33ff)
```

`gap048-through-junction` must not be merged *after* topology: topology already
carries the identical patch, so it is retired, not sequenced.

## Recommended order + tests per step

| # | step | mode | tests after |
|---|---|---|---|
| 1 | `fix/gap049-poller-delta-only` | fast-forward | `test_package_write_poller*.py`, `test_cook_resource_census.py`, `test_stall_watchdog.py` |
| 2 | `fix/topology-convergence` | fast-forward | full bare pytest + `pytest -k lane_successor_topency` |
| 3 | resolve GAP-055 twin | **review, do not merge blind** | `pytest --collect-only` must exit 0 (GAP-047 guard) |
| 4 | `rq2-authority` | cherry-pick `56a82a35`, `2159a358` | `test_gate_class_registry_coverage.py`, `test_waiver_taxonomy.py`, RQ2 metric tests |
| 5 | `rq5-readiness` | cherry-pick `9474894f`, `7a2310c2` | `pytest -k rq5` |

## Expected conflicts

- **GAP-055 twin**: divergent patch-ids behind a clean textual merge (above).
- **tools/\***: conflict is a symptom of prior absorption, not a real conflict.
- **rq2-authority / rq5-readiness**: merge-base `7fbd33ff`, 40 behind — direct
  merge would replay the divergent base; replay the 2 exact commits instead.

## Do-not-merge set

| branch | class |
|---|---|
| fix/gap048-through-junction-20261009 | PATCH_ALREADY_PRESENT (identical patch-id to topology) |
| tools/rq1-stage-profiler-20261008 | PATCH_ALREADY_PRESENT |
| tools/cook-diagnostics-harness-20261008 | PATCH_ALREADY_PRESENT |
| tools/gap017-diagnostic-toolkit-20261008 | PATCH_ALREADY_PRESENT |
| fix/gap055-ci-windll-platform-guard-20261011 | REVIEW_REQUIRED until the twin divergence is resolved |

No rescue branch is recommended for wholesale merge.

## Artifacts

- `reports/repository_convergence/MERGE_DEPENDENCY_DAG.json`
- `reports/repository_convergence/MERGE_DEPENDENCY_DAG.md` (this file)
- `reports/repository_convergence/MERGE_SIMULATION_MATRIX.json`