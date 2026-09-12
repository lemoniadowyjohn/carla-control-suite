# Target Pipeline Stage Graph

Status: proposed architecture, informed by a direct read of the live pipeline (`ultimate_pipeline/main_pipeline.py`,
`pipeline_stages/*`) as of baseline `2e020d9b`. This document does not change any code. Full raw findings:
`reports/production_readiness/20260906T170000Z/PIPELINE_DEPENDENCY_GRAPH.json`.

## Current (live) stage order

```
1  sanitize
2  topology_semantics       (repairs dangling junction refs, topology lint)
3  topology_repair
4  enrichment                (roundabout tagging/reconstruction, buildings, signals,
                              crosswalks, signs, traffic lights -- BEFORE lanes exist)
5  geometry_elevation        (embeds "6" as its first sub-step, then freezes XY, then DEM)
   6  planview_continuity    (governed containment: read-only outside DEVELOPMENT profile)
7  lanes                     (asserts geometry frozen at entry)
8  integrity_lanelinks       (authoritative "final_out" switch point)
8H hygiene                   (island quarantine, lane-width repair, z-seam chaining)
9  tiling
10 tile_qa                   (CARLA-gated, skips if unreachable)
11 simulation                (interactive-only, dead in automated runs)
12 domain_gap                (read-only comparison vs. manual map)
```

## Why this is not simply "wrong ordering"

The most consequential finding from this audit's architecture review is **negative**: the widely-assumed
explanation for Stage 6's containment mode -- "the pipeline stages run in the wrong order" -- does not hold up
against the code. Every "unsafe" mutator gated behind `EXPERIMENTAL_UNSAFE` (`smooth_heading_jumps`,
`merge_small_geometries`, `merge_short_segments`, `recompute_geometry_starts`, `clamp_curvature`) is internally
incomplete or was previously buggy **within a single function call**, independent of which stage calls it or when:

- `smooth_heading_jumps` mutates a geometry's `hdg` without touching that geometry's or any downstream geometry's
  `x`/`y` -- a missing companion step, not a stage-ordering problem.
- `recompute_geometry_starts_chained_inplace` (the companion fix) has its own, narrower defect: it mishandles
  `paramPoly3` geometries whose declared length doesn't match true parametric arc length. A guard was added
  2026-09-04 (commit `21cc6430`) to skip re-chaining across such a boundary, but **no end-to-end rerun of the full
  heading-smoothing scenario against this guard has been documented** -- this needs verification before the
  containment mode can be safely relaxed for this flag.
- `clamp_curvature` is already applied **unconditionally**, ungated, later in stage 5 (`stage_05_geometry.py:1037`)
  -- meaning the stage-6-gated curvature flag is largely redundant with a path that already runs in production.

**Conclusion: reordering stages will not fix Stage-6 containment.** The path to safely relaxing containment is
fixing the internal defects in each mutator (verified via golden-equivalence tests, following the pattern stage
6 already uses for its own containment diff), not moving stage boundaries around.

## Where reordering IS a real improvement

Two concrete, evidence-backed changes to the live order are worth making:

1. **Move buildings/signals/crosswalks to run after lane generation and structural freeze**, not before (as they
   do today in stage 4). Stage 4 already declares `semantic_state["has_lanes"] = False` and is documented as
   "geometry-only" -- no code was found that requires lane generation (stage 7) to happen after stage 4's
   semantic enrichment. This looks like a historical artifact of how the monolithic pipeline was split into
   files, not a real dependency. Moving it doesn't change behavior on its own, but it removes a standing
   architectural question mark and makes the real dependency graph match the code's own stated contract.

2. **Promote the geometry-freeze mechanism to an explicit, first-class stage.** It already exists
   (`geometryFrozen`/`geometryFreezeHash` header attributes + `_assert_geometry_frozen`, asserted at the entry
   of stages 7 and 8) but is currently buried inside stage 5's function body rather than being its own stage
   with its own gate/report. This is low-risk (it's already conceptually separate) and would make the pipeline's
   most load-bearing invariant visible in the stage graph instead of implicit in a function.

## Proposed order (revised from the brief, informed by the above)

```
1  pinned input ingest
2  base OSM->XODR conversion
3  topology normalization                (current stages 2-3)
4  horizontal geometry normalization      (current stage 6's real work, un-contained
                                           once its internal defects are fixed and verified)
5  junction/connector geometry            (current opt-in connector-rebuild step)
6  roundabout structural reconstruction   (NOT independently confirmed whether this needs
                                           to run before or after #4/#5 -- roundabout_reconstructor.py's
                                           own geometric assumptions were not read in this pass; verify
                                           before implementing this specific ordering change)
7  elevation/structures                   (current stage 5's DEM application)
8  lane/cross-section model               (current stage 7 -- must stay after #4-#7, unchanged)
9  STRUCTURAL FREEZE                      (promoted to explicit stage, see above)
10 spatial OSM<->XODR semantic correspondence  (NEW -- see GAP-005 in the gap register;
                                           currently this doesn't exist as a stage at all,
                                           correspondence is ad hoc per-enrichment-module)
11 signals/signs/crosswalks/buildings     (moved here from current stage 4, see above)
12 visual/collision enrichment            (Phase J tooling, currently a standalone tool
                                           not wired into main_pipeline.py at all -- see
                                           GAP-013)
13 offline production acceptance          (unify existing quality-gate system, see
                                           PRODUCTION_MAP_QUALITY_CONTRACT.yaml)
14 runtime certification                  (live CARLA, NOT_RUN until authorized)
```

## Explicitly not resolved by this document

- Whether roundabout reconstruction genuinely needs to precede or follow horizontal-geometry normalization is
  an open question -- flagged for Codex/whoever implements this to verify against `roundabout_reconstructor.py`
  directly before committing to stage 6's position above.
- The earliest two stages ("pinned input ingest", "base OSM->XODR conversion") precede
  `ultimate_pipeline`'s own stage numbering and were not audited in this pass.
- This is a target for a **future, incremental** migration (see `PRODUCTION_MAP_TASK_GRAPH.json`). No stage
  code was changed to produce this document.
