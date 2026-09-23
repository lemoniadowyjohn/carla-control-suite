# F: drive worktree audit — 2026-09-24

Audited: 2026-09-24 (no deletion, move, cleanup, or Git maintenance was
performed). This report is a review queue, not authorization to remove any
path.

## Baseline and exclusions

* Production baseline inspected: `origin/integration/production-large-map-20260918`
  at `77b6bbfe4fd155196f7f18e1fdf774db239c0b82`.
* Space at audit time: C: 672.32 GiB used, 0.74 GiB free; F: 672.32 GiB used,
  0.74 GiB free.
* All 31 F: drive worktrees are merged into `origin/integration/production-large-map-20260918`.
* No Git object directory, source file, map-of-record candidate file, or report
  JSON/Markdown content is proposed for deletion.
* The current campaign manifest identifies its governed XODR payloads in
  `campaigns/ingolstadt_cooked_perception_v1/candidate/`; it does not identify
  any `campaigns/ingolstadt_cooked_perception_v1/regen/` directory as the
  current map-of-record. A coordinator must nevertheless verify any selected
  run against the current artifact receipt before removal.

## F: drive worktree inventory

| Worktree path | Branch | Merged into integration | Size |
| --- | --- | --- | ---: |
| `F:\carla-control-suite-worktrees\artifact-locator-staleness-v1-20260916` | `fix/artifact-locator-staleness-resolution-v1-20260916` | YES | 3.72 GiB |
| `F:\carla-control-suite-worktrees\building-road-residual-offset-v1-20260914` | `feature/building-road-residual-offset-v1-20260914` | YES | 3.58 GiB |
| `F:\carla-control-suite-worktrees\confirmed-hygiene-gaps-v1-20260914` | `feature/confirmed-hygiene-gaps-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\crosswalk-writer-idempotency-v1-20260914` | `feature/crosswalk-writer-idempotency-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\dem-crs-elevation-v2` | `audit/dem-crs-elevation-v2` | YES | 3.70 GiB |
| `F:\carla-control-suite-worktrees\deterministic-alignment-offset-contract-v1-20260914` | `feature/deterministic-alignment-offset-contract-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\domain-gap-gnn-v2` | `fix/rq4-gnn-provenance-leakage-v1-20260922` | YES | 3.84 GiB |
| `F:\carla-control-suite-worktrees\evidence-integrity-v2` | `audit/evidence-integrity-v2` | YES | 3.72 GiB |
| `F:\carla-control-suite-worktrees\fbx-regen-current-pin-v1-20260915` | `feature/fbx-regen-current-pin-v1-20260915` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\geometry-topology-oracle-v2` | `audit/geometry-topology-oracle-v2-20260915` | YES | 3.70 GiB |
| `F:\carla-control-suite-worktrees\grid-unstable-map-mitigation-tests-v1-20260915` | `feature/grid-unstable-map-mitigation-tests-v1-20260915` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\malformed-xodr-fix-clean` | `fix/malformed-xodr-attrs-v3-20260916` | YES | 3.70 GiB |
| `F:\carla-control-suite-worktrees\manual-grid-rca` | `rca/manual-grid-0821-0828-v2` | YES | 3.70 GiB |
| `F:\carla-control-suite-worktrees\oc1-independent-review` | `fix/geometry-crs-dem-correctness-v1-20260915` | YES | 3.70 GiB |
| `F:\carla-control-suite-worktrees\osm-road-link-topology-crosscheck-v1-20260914` | `feature/osm-road-link-topology-crosscheck-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\parampoly3-blind-spot-sweep-v1-20260914` | `feature/parampoly3-blind-spot-sweep-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\roundabout-v2-materialization-v1-20260914` | `feature/roundabout-v2-materialization-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\roundabout-v2-real-map-validation-v1-20260913` | `feature/roundabout-v2-real-map-validation-v1-20260913` | YES | 3.58 GiB |
| `F:\carla-control-suite-worktrees\roundabout-v2-source-aware-detection-v1-20260913` | `feature/roundabout-v2-source-aware-detection-v1-20260913` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\rq3-paired-capture-protocol-mismatch-v1-20260916` | `fix/rq3-paired-capture-protocol-mismatch-v1-20260916` | YES | 3.72 GiB |
| `F:\carla-control-suite-worktrees\rq5a-training-launcher-synthetic-dry-run-v1-20260916` | `test/rq5a-training-launcher-synthetic-dry-run-v1-20260916` | YES | 3.72 GiB |
| `F:\carla-control-suite-worktrees\runtime-tile-subset-v1-20260914` | `feature/runtime-tile-subset-v1-20260914` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\semantic-organizer` | `docs/sync-rq3-carla-diagnosis-v1-20260917` | YES | 3.86 GiB |
| `F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913` | `integration/production-large-map-20260918` | YES | 3.86 GiB |
| `F:\carla-control-suite-worktrees\structure-elevation-crs-blocker-v1-20260913` | `feature/structure-elevation-crs-blocker-v1-20260913` | YES | 3.58 GiB |
| `F:\carla-control-suite-worktrees\structure-elevation-remediation-v1-20260913` | `feature/structure-elevation-remediation-v1-20260913` | YES | 3.59 GiB |
| `F:\carla-control-suite-worktrees\tile-based-ue4-cooking-design-v1-20260915` | `docs/tile-based-ue4-cooking-design-v1-20260915` | YES | 0.13 GiB |
| `F:\carla-control-suite-worktrees\ue4-large-map` | `feature/ue4-large-map-production-v2` | YES | 3.70 GiB |
| `F:\gap016-worktree` | `fix/gap-016-receipt-authority-20260922` | YES | 3.86 GiB |
| `F:\rq4-worktree` | `fix/rq4-gnn-experimental-provenance-v1-20260921` | YES | 3.86 GiB |
| `F:\rq5-worktree` | `fix/rq5-thesis-evidence-governance-v1-20260919` | YES | 3.86 GiB |

**Totals**: 31 worktrees, approximately **115.4 GiB** total disk usage on F:.
F: drive free space: **0.74 GiB**.

## Status and merge verification

All 31 F: drive worktrees are confirmed merged into `origin/integration/production-large-map-20260918`
at `77b6bbfe`. No worktree carries unmerged commits relative to the production
baseline. Working tree status for each worktree was recorded; only
`F:\gap016-worktree`, `F:\rq4-worktree`, `F:\rq5-worktree`, and
`F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913` have
untracked `reports/production_readiness/*_TILE_BASED_FBX_GENERATION_PROBE`
directories.

## Ranked candidates requiring coordinator approval

| Rank | Candidate path | Measured size | Why it is reclaimable-without-risk candidate |
| --- | --- | ---: | --- |
| 1 | `F:\carla-control-suite-worktrees\semantic-organizer` | 3.86 GiB | Worktree on `docs/sync-rq3-carla-diagnosis-v1-20260917`; fully merged into integration. |
| 2 | `F:\carla-control-suite-worktrees\session-batch1-full-verify-20260913` | 3.86 GiB | Worktree directly on `integration/production-large-map-20260918`; fully merged. |
| 3 | `F:\gap016-worktree` | 3.86 GiB | Worktree on `fix/gap-016-receipt-authority-20260922`; fully merged into integration. |
| 4 | `F:\rq4-worktree` | 3.86 GiB | Worktree on `fix/rq4-gnn-experimental-provenance-v1-20260921`; fully merged into integration. |
| 5 | `F:\rq5-worktree` | 3.86 GiB | Worktree on `fix/rq5-thesis-evidence-governance-v1-20260919`; fully merged into integration. |
| 6 | `F:\carla-control-suite-worktrees\domain-gap-gnn-v2` | 3.84 GiB | Worktree on `fix/rq4-gnn-provenance-leakage-v1-20260922`; fully merged into integration. |
| 7 | `F:\carla-control-suite-worktrees\evidence-integrity-v2` | 3.72 GiB | Worktree on `audit/evidence-integrity-v2`; fully merged into integration. |
| 8 | `F:\carla-control-suite-worktrees\artifact-locator-staleness-v1-20260916` | 3.72 GiB | Worktree on `fix/artifact-locator-staleness-resolution-v1-20260916`; fully merged into integration. |
| 9 | `F:\carla-control-suite-worktrees\rq3-paired-capture-protocol-mismatch-v1-20260916` | 3.72 GiB | Worktree on `fix/rq3-paired-capture-protocol-mismatch-v1-20260916`; fully merged into integration. |
| 10 | `F:\carla-control-suite-worktrees\rq5a-training-launcher-synthetic-dry-run-v1-20260916` | 3.72 GiB | Worktree on `test/rq5a-training-launcher-synthetic-dry-run-v1-20260916`; fully merged into integration. |
| 11 | `F:\carla-control-suite-worktrees\dem-crs-elevation-v2` | 3.70 GiB | Worktree on `audit/dem-crs-elevation-v2`; fully merged into integration. |
| 12 | `F:\carla-control-suite-worktrees\manual-grid-rca` | 3.70 GiB | Worktree on `rca/manual-grid-0821-0828-v2`; fully merged into integration. |
| 13 | `F:\carla-control-suite-worktrees\oc1-independent-review` | 3.70 GiB | Worktree on `fix/geometry-crs-dem-correctness-v1-20260915`; fully merged into integration. |
| 14 | `F:\carla-control-suite-worktrees\malformed-xodr-fix-clean` | 3.70 GiB | Worktree on `fix/malformed-xodr-attrs-v3-20260916`; fully merged into integration. |
| 15 | `F:\carla-control-suite-worktrees\geometry-topology-oracle-v2` | 3.70 GiB | Worktree on `audit/geometry-topology-oracle-v2-20260915`; fully merged into integration. |
| 16 | `F:\carla-control-suite-worktrees\ue4-large-map` | 3.70 GiB | Worktree on `feature/ue4-large-map-production-v2`; fully merged into integration. |
| 17 | `F:\carla-control-suite-worktrees\crosswalk-writer-idempotency-v1-20260914` | 3.59 GiB | Worktree on `feature/crosswalk-writer-idempotency-v1-20260914`; fully merged into integration. |
| 18 | `F:\carla-control-suite-worktrees\confirmed-hygiene-gaps-v1-20260914` | 3.59 GiB | Worktree on `feature/confirmed-hygiene-gaps-v1-20260914`; fully merged into integration. |
| 19 | `F:\carla-control-suite-worktrees\deterministic-alignment-offset-contract-v1-20260914` | 3.59 GiB | Worktree on `feature/deterministic-alignment-offset-contract-v1-20260914`; fully merged into integration. |
| 20 | `F:\carla-control-suite-worktrees\fbx-regen-current-pin-v1-20260915` | 3.59 GiB | Worktree on `feature/fbx-regen-current-pin-v1-20260915`; fully merged into integration. |
| 21 | `F:\carla-control-suite-worktrees\grid-unstable-map-mitigation-tests-v1-20260915` | 3.59 GiB | Worktree on `feature/grid-unstable-map-mitigation-tests-v1-20260915`; fully merged into integration. |
| 22 | `F:\carla-control-suite-worktrees\osm-road-link-topology-crosscheck-v1-20260914` | 3.59 GiB | Worktree on `feature/osm-road-link-topology-crosscheck-v1-20260914`; fully merged into integration. |
| 23 | `F:\carla-control-suite-worktrees\parampoly3-blind-spot-sweep-v1-20260914` | 3.59 GiB | Worktree on `feature/parampoly3-blind-spot-sweep-v1-20260914`; fully merged into integration. |
| 24 | `F:\carla-control-suite-worktrees\roundabout-v2-materialization-v1-20260914` | 3.59 GiB | Worktree on `feature/roundabout-v2-materialization-v1-20260914`; fully merged into integration. |
| 25 | `F:\carla-control-suite-worktrees\roundabout-v2-source-aware-detection-v1-20260913` | 3.59 GiB | Worktree on `feature/roundabout-v2-source-aware-detection-v1-20260913`; fully merged into integration. |
| 26 | `F:\carla-control-suite-worktrees\runtime-tile-subset-v1-20260914` | 3.59 GiB | Worktree on `feature/runtime-tile-subset-v1-20260914`; fully merged into integration. |
| 27 | `F:\carla-control-suite-worktrees\structure-elevation-remediation-v1-20260913` | 3.59 GiB | Worktree on `feature/structure-elevation-remediation-v1-20260913`; fully merged into integration. |
| 28 | `F:\carla-control-suite-worktrees\building-road-residual-offset-v1-20260914` | 3.58 GiB | Worktree on `feature/building-road-residual-offset-v1-20260914`; fully merged into integration. |
| 29 | `F:\carla-control-suite-worktrees\roundabout-v2-real-map-validation-v1-20260913` | 3.58 GiB | Worktree on `feature/roundabout-v2-real-map-validation-v1-20260913`; fully merged into integration. |
| 30 | `F:\carla-control-suite-worktrees\structure-elevation-crs-blocker-v1-20260913` | 3.58 GiB | Worktree on `feature/structure-elevation-crs-blocker-v1-20260913`; fully merged into integration. |
| 31 | `F:\carla-control-suite-worktrees\tile-based-ue4-cooking-design-v1-20260915` | 0.13 GiB | Worktree on `docs/tile-based-ue4-cooking-design-v1-20260915`; fully merged into integration. |

## F: drive space emergency

F: drive has **0.74 GiB free** out of 672.32 GiB used. This is critically
low. Any of the 31 worktrees could be removed to restore adequate free space,
but all are fully merged into the production integration branch and carry no
unmerged commits.

## Recommended safe next action

1. Coordinator selects a small, explicit subset of F: drive worktrees to
   remove (prioritizing the largest or oldest worktrees).
2. Before removal, independently confirm each selected worktree's branch is
   fully merged into `origin/integration/production-large-map-20260918`
   and that no active process is using files within the worktree.
3. Remove selected worktrees using `git worktree remove --force <path>`,
   then remeasure F: drive free space and record the action in a separate
   deletion log.
4. Treat F: cleanup as urgent due to the 0.74 GiB free space condition.
   Do not touch active worktrees, Git objects, or unreviewed evidence
   without their owners' confirmation.
