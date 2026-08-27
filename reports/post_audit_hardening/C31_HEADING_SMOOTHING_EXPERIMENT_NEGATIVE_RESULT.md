# C31 — heading-only smoothing experiment: confirmed unsafe, do not enable

User decision (2026-08-27): "Enable the unsafe heading smoothing and run a regen" — follow-up
to C30's finding of 48 roads with position-continuous heading kinks and the identification of
an existing-but-disabled fix (`PlanViewSmoother.smooth_heading_jumps`, gated behind
`ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING`).

## What was run
`scripts/regen_experimental_heading_smoothing.py` (new): runs the full pipeline with
`RELEASE_PROFILE=EXPERIMENTAL_UNSAFE`, `THESIS_STRICT=0`, `ENABLE_UNSAFE_PLANVIEW_MUTATIONS=1`,
`ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING=1` — every other individual `ENABLE_UNSAFE_*` flag left
at its own default `False`, so only heading smoothing is under test. Reused the exact same
pinned seed XODR that produced the current map of record
(`campaigns/.../regen/20260819T142310Z/seed_from_osm.xodr`, sha `c32d136a...`) rather than
re-running Osm2Odr, isolating the experiment to this one variable.

Not run through `regen_map_of_record.py`'s own CLI: its `--profile` argparse choices
deliberately exclude `EXPERIMENTAL_UNSAFE` (canonical map-of-record candidates must never be
generated under a profile that also relaxes `STRICT_QUALITY_GATES`/`STRICT_TILE_SEMANTICS`/
`ALLOW_FALLBACK_MAP`/`ALLOW_TILE_QA_SKIP` — bundled together by design in
`ultimate_pipeline/config/settings.py`'s `RELEASE_PROFILES` table). The new script reuses the
same internal functions (`_run_pipeline`, `_find_final_xodr`, `_rebase_to_local`) rather than
reimplementing them.

## A real hurdle hit and fixed along the way
First attempt failed instantly with a misleading `"SUMO is not available"` error. Root cause:
`Settings._apply_release_profile()` fail-closed-checks every individual `ENABLE_UNSAFE_*` flag
against the **current process's own** release profile at settings-init time — I had correctly
passed `"EXPERIMENTAL_UNSAFE"` as the `profile` argument to `_run_pipeline` (which sets it for
the **subprocess**'s env), but never set `UP_RELEASE_PROFILE` in the **wrapper script's own**
process environment. With the wrapper's own profile still at its `DEVELOPMENT` default while
the unsafe flag was set via env, the fail-closed guard correctly raised
`RuntimeError: RELEASE_PROFILE=DEVELOPMENT forbids ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING=True`
— but that exception was silently swallowed by `_sumo_status()`'s broad `except Exception: pass`,
surfacing only as an unrelated, confusing SUMO-not-found message. Fixed by also setting
`UP_RELEASE_PROFILE=EXPERIMENTAL_UNSAFE` in the wrapper's own environment before any pipeline
imports. Confirmed the exact failure mode reproduces and resolves via a standalone diagnostic
before re-running the real (expensive) regen.

## Result — the map got worse, not better
Independent verification, deliberately run in **two separate steps** so the acceptance check
couldn't inherit the relaxed generation-time settings:

1. **Structural signature vs. the current pin** (`--verify-structural`): road/junction counts
   identical (32,297 / 3,568 — matches C15's determinism finding), `total_road_length` differs
   by ~13 m out of 1,495,647 m (0.0009%) — smoothing did modify geometry, just not much of it
   in aggregate.
2. **`regen_map_of_record.py --verify-only`** (fresh process, clean env — no unsafe/strict
   overrides): `valid_for_experiments=True`, all hard-fail gates pass, same single
   pre-existing WARN as baseline (33 isolated lane components). Looked clean.
3. **`check_planview_internal_seams`** directly (the actual function under test, and the
   source of the 48-road finding this whole experiment was meant to address):

   | | baseline (current pin) | after heading smoothing |
   |---|---|---|
   | `ok` | `True` | **`False`** |
   | `num_seams` (real position gaps, `dxy>0.2m`) | 0 | **6,024** |
   | `num_heading_only_discontinuities` (rows) | 82 | **1,334** |
   | distinct affected roads | 48 | **918** |

   Heading smoothing made **both** metrics dramatically worse — not a partial improvement
   with some regression, a comprehensive regression. It introduced 6,024 brand-new real
   position discontinuities where there were zero before, while the position-continuous
   heading-kink count it was meant to fix went up roughly 19× rather than down.

**Why step 2 looked clean despite this**: confirmed by reading
`scripts/measure_candidate_acceptance.py` — the acceptance gate `--verify-only` runs calls
`check_geometric_continuity` (the road-to-road **link** check) only. It never calls
`check_planview_internal_seams` (the **intra-road** check) at all. This is not new to this
experiment — it's a pre-existing characteristic of the acceptance gate's coverage, on both the
baseline pin and this candidate alike. Flagging it here because this experiment is what
surfaced it, not proposing a fix to the gate in this pass.

## Conclusion
`PlanViewSmoother.smooth_heading_jumps(threshold_deg=12.0)`, as currently implemented, is
**confirmed unsafe on this real map** — concrete, measured evidence, not a theoretical concern.
This validates the pipeline's prior deliberate decision to keep it disabled by default; that
decision was correct. **Recommendation: do not enable `ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING`
for any governed regen.** The original 48-road heading-kink defect (C30) remains unaddressed —
a real fix would need a materially different, more targeted approach than blanket
threshold-based smoothing (e.g. only touching genuinely isolated line-to-line kinks rather than
resampling/adjusting the surrounding curve fit, which is what most plausibly introduced the
6,024 new seams here).

## Artifacts
- `scripts/regen_experimental_heading_smoothing.py` — the experiment harness, kept (a real,
  reusable, well-documented tool; this negative result doesn't make the harness itself wrong,
  and a future, more careful smoothing attempt could reuse it).
- Experimental candidate: `campaigns/.../candidate/EXPERIMENTAL_heading_smoothing_20260827_142533.xodr`
  (sha `91277e2ffbbba3f9d00eb336472f1ab2ff292ac18aeb5495c4efa6c26d982ddb`) — **not promoted, not
  a governed candidate, must not be treated as one.** Kept on disk (git-ignored, same as every
  other non-promoted candidate variant) purely as the artifact this measurement was taken
  against, for reproducibility of this report's numbers.
- Regen run directory:
  `campaigns/.../regen/20260827T135439Z_EXPERIMENTAL_heading_smoothing/` (git-ignored).

## Verification
- Full unit suite: unaffected by this experiment (no pipeline/gate code was modified — only a
  new, standalone harness script was added). See commit for exact pass count.
- All numbers above independently re-derived directly against the real emitted artifact, not
  taken from in-pipeline self-reported logs.
