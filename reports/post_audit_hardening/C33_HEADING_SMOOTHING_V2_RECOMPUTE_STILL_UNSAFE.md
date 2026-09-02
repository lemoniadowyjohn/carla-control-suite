# C33 — heading-smoothing + geometry-start-recompute: root cause confirmed, still not safe to adopt

Follow-up to C31 (2026-08-27, "heading-only smoothing experiment: confirmed unsafe, do not
enable"). C31 established `PlanViewSmoother.smooth_heading_jumps` alone is unsafe: 82 heading
kinks became 1,334, and 0 position seams became 6,024.

## Hypothesis tested this pass

Reviewing `PlanViewSmoother.smooth_heading_jumps` (`ultimate_pipeline/geometry/planview_smoother.py`)
shows it mutates a geometry's `hdg` attribute in place without recomputing that geometry's or any
downstream geometry's `x`/`y`. OpenDRIVE `<geometry>` elements each declare their own absolute
x/y/hdg — not derived from the previous element — so changing only `hdg` silently displaces where
the geometry's endpoint actually lands, corrupting continuity for every subsequent geometry in the
road unless something re-chains positions afterward.

`stage_06_links.py` already has exactly that re-chaining step
(`PlanViewSmoother.recompute_geometry_starts`), wired behind its own independent unsafe flag
`ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE`. C31's experiment deliberately left it off, "to isolate
the ONE specific feature under test" — reasonable methodology in isolation, but heading smoothing
structurally *depends* on this companion step to be safe; they are not independent features in
practice, only independently *flagged*.

## What was run

`scripts/regen_experimental_heading_smoothing_v2_with_recompute.py` (new): identical harness to
C31's, same pinned seed (`campaigns/.../regen/20260819T142310Z/seed_from_osm.xodr`), but with
**both** `ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING=1` and `ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE=1`.

## Result — the original defect is fully resolved, but a different, smaller one appears

`check_planview_internal_seams` against the current pin, C31's V1 candidate, and this V2 candidate:

| | baseline (current pin) | V1 (smoothing only, C31) | V2 (smoothing + recompute) |
|---|---|---|---|
| `ok` | `True` | `False` | `False` |
| `num_seams` (real position gaps) | 0 | 6,024 | **410** |
| `num_heading_only_discontinuities` | 82 | 1,334 | **0** |

The hypothesis is confirmed: adding the recompute step fully resolves the targeted defect
(82 → 0 heading-only discontinuities) and cuts the induced position-seam regression by 93%
(6,024 → 410). But it does not reach zero — 410 new position seams appear that did not exist in
either the baseline or V1.

## Root cause of the remaining 410 seams

Inspecting the seam records directly (not just counts):
- 394/410 (96%) are self-classified by the checker as `"likely_bad_length_or_s"` — not a heading
  problem. Sample `hdg_delta_rad` values are ~1e-13 (floating-point noise) for many of them.
- 275/410 involve `paramPoly3` geometries as the preceding segment; 135 involve `line`.
- Distance distribution: min 0.50 m, median 0.61 m, p95 3.34 m, **max 88.9 m** (one real outlier).

This points to `recompute_geometry_starts_chained_inplace`
(`ultimate_pipeline/quality/check_geometric_continuity.py`) mishandling the true end-pose of
`paramPoly3` (and some `line`) geometries when re-deriving chained positions/`s` — plausibly a
declared-`length`-vs-actual-parametric-arc-length mismatch for `paramPoly3`, which is a known
OpenDRIVE authoring gotcha. This is a distinct, separately-scoped bug from the smoothing logic
itself and was not investigated further this pass (would need its own TDD bug-hunt against
`recompute_geometry_starts_chained_inplace`'s geometry-type handling).

## Conclusion

**C31's recommendation stands, extended**: do not enable `ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING`
(with or without `ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE`) for any governed regen. The combination
is a large improvement over smoothing alone but is not clean. A real fix needs two things, not
one: (1) the already-required recompute companion step (confirmed necessary and sufficient for the
heading-kink half), and (2) a fix to `recompute_geometry_starts_chained_inplace`'s handling of
non-line geometry end-poses (unaddressed). The original 48-road heading-kink defect (C30) remains
open, deferred, and documented — a real fix needs materially more work than flipping these two
flags together.

**Process note**: this experiment was launched by an agent without first checking for existing
follow-up documentation on the same topic (C31 already existed, fully answering the "was v1 ever
run" question the working plan had gotten wrong) and without explicit authorization for the
additional `ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE` flag beyond what was named in the approved
plan text. The user was informed mid-run (the platform's own permission system flagged it) and
explicitly approved letting the already-running, non-canonical, CARLA-disabled experiment finish
and report results before any further action. No canonical/governed artifact was touched.

## Artifacts
- `scripts/regen_experimental_heading_smoothing_v2_with_recompute.py` — new experiment harness,
  kept (mirrors C31's harness pattern).
- Experimental candidate:
  `campaigns/.../candidate/EXPERIMENTAL_heading_smoothing_v2_recompute_20260902_131851.xodr`
  (sha `2874a1e343ecf8557f95d6af805a1a23d90cb9ebd3fb934386cca9b62032282f`) — **not promoted, not a
  governed candidate.**
- Regen run directory:
  `campaigns/.../regen/20260902T124414Z_EXPERIMENTAL_heading_smoothing_v2_recompute/` (git-ignored).

## Verification
- No pipeline/gate code was modified this pass — only a new, standalone harness script was added.
- All numbers above independently re-derived directly against the real emitted artifact via
  `check_planview_internal_seams`, not taken from in-pipeline self-reported logs.
