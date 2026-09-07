# Production Map Remediation Plan

Narrative companion to `PRODUCTION_MAP_TASK_GRAPH.json` (the machine-readable version — read that for
exact dependency IDs, affected files, tests, and stop conditions). This document explains the
sequencing logic in prose.

## Why this order

The 26 tasks are sequenced around one structural fact: **lane count (T-001) is the most upstream real
defect** (`MAP_QUALITY_GAP_REGISTER.json` GAP-001). Every road currently gets exactly one driving lane
per side regardless of OSM data. Turn-lane geometry (T-015), lane-count-change gating (T-018), lane
provenance metadata (T-017), and roundabout multi-lane preservation (T-007) all depend on T-001 landing
first — building any of them against the current single-lane-everywhere generator would mean building
on top of a foundation that's about to change shape.

The second cluster (T-002, T-004) addresses the junction-connector layer: `ConnectorValidator`'s
disabled checks and the newly-quantified 20.3%-offset finding are two views of the same underlying
gap — connector poses aren't validated, and a large fraction of them are measurably wrong by exactly
one lane-width. These should be worked together, not sequentially, since fixing the validator will
directly inform how the offset gets corrected.

T-003 is deliberately scoped as **documentation, not remediation** — the 27 isolated lane components
were independently re-derived and re-confirmed this audit as a genuine "zero valid connector
candidates" defect whose only real fix would mean fabricating geometry that doesn't exist in the
source data. That conclusion was reached once already (see `project_round4_junction_connection_coverage_20260904`
in this repo's session memory) and holds up under a fresh, independent trace. Re-attempting a
geometric fix here without new evidence would waste effort and risk exactly the kind of
threshold-lowering or synthetic-geometry stop condition this audit was told to watch for.

T-006 (the second-city fixture) has no code dependency and can start immediately, in parallel with
everything else — it's purely a data-acquisition task for the operator. Every structural-algorithm
task (T-001, T-002, T-007, T-009) should be re-validated against it once it exists, but none of them
need to wait for it to *start*.

T-026 (wiring the `production_candidate` acceptance profile) is deliberately last. It depends on ten
earlier tasks because it's the unification step — building it before the new gates it references exist
would just mean stubbing them out, defeating the point.

## What this plan does not include

- Any task requiring live CARLA (`requires_live_carla: true` appears nowhere in the current task
  graph — every task is either offline-code, offline-data, or an operator policy decision). This
  matches the audit's own STOP condition: "fix would require live CARLA."
- Any task that would fabricate geometry to force a metric down (the T-003 scoping note above is the
  concrete instance of this discipline).
- Any task touching frozen thesis evidence, `submission/infrastructure/`, or GitHub
  branch-protection/default-branch settings.
- A full StageContext migration (T-014 is scoped to *begin* it, on the single lowest-risk target
  `self.semantic_state`, explicitly excluding stages 5/6/8 from this first pass).

## Sequencing summary (informal, see the JSON for the authoritative dependency graph)

```
Immediately startable (no dependencies):
  T-002, T-003, T-004, T-005, T-006, T-008, T-009, T-010, T-011, T-012,
  T-013, T-014, T-016, T-019, T-020, T-021, T-022, T-024, T-025

Depend on T-001 (lane count from OSM):
  T-007 (roundabout multi-lane), T-015 (turn/cycle lanes),
  T-017 (lane provenance), T-018 (lane-count-change gate)

Depend on T-011 (Phase J wiring):
  T-023 (z-fighting detector)

Last (depends on 10 earlier tasks):
  T-026 (production_candidate profile wiring)
```

## The single next admissible task

Per this audit's closing verdict, **T-001** is the recommended starting point for Codex: it is the
highest-priority (P0), most foundational, has zero dependencies, is precisely scoped, and does not
require live CARLA. See `PRODUCTION_MAP_TASK_GRAPH.json` for its full task definition.
