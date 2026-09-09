# Codex — PROMPT Q: F5's graph-relaxation elevation-seam solver vs. the live local fixer

## Context

Continuing the "phase_*" wiring audit (already found Phase H dark-but-tested, Phase G6
dark-but-tested). `ultimate_pipeline/tools/phase_f5_bounded_offsets.py` ("F5") implements a
deterministic graph-relaxation link-offset solver for road-to-road elevation seams. Its sibling
`phase_f7_final_verification.py` explicitly documents a correctness claim about it, in its own
generated evidence markdown: "The offset-solver candidate (F5) is the verified final elevation
candidate: its global graph relaxation correctly resolves the map's cyclic / multi-predecessor
junction topology. The local seam fixer (F6) is available for acyclic networks but over-blends
endpoints already adjusted by F5 on junctioned graphs, so F5 is gated as final."

Real execution evidence exists (reports/post_audit_hardening/20260803T160000Z/F5_BOUNDED_OFFSETS.{json,md}):
32,647 per-road vertical offsets applied, 45,632 road-to-road seams checked, worst-case seam delta
reduced from 5.129m (1 over threshold) to 3.036m (0 over threshold), all slopes (b/c/d coefficients)
and topology/geometry provably untouched (only each segment's constant `a` term shifted). This is
not a toy result.

F5 has ZERO references anywhere in the live pipeline (ultimate_pipeline/pipeline_stages/,
main_pipeline.py) or the campaign-script cluster -- confirmed via grep. What IS live, wired into
stage_08_hygiene.py's step 8H-3, is `repair_true_zseams` (ultimate_pipeline/quality/map_hygiene.py:448)
-- a DIFFERENT function, not literally phase_f6_seam_repair.py. Whether `repair_true_zseams` is the
same algorithm class as the "local seam fixer (F6)" F7's evidence criticizes, or a third,
independently-written approach with its own (possibly different) characteristics, has NOT been
confirmed -- this is the first thing to establish, not an assumption to build on.

## PROMPT Q

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/f5-elevation-solver-v1-<date>.

This is investigation first, same discipline as this session's other phase-module findings: do not
modify the map-of-record or wire anything into the live pipeline until every step below is done.

TASK:
1. Read ultimate_pipeline/tools/phase_f5_bounded_offsets.py and phase_f7_final_verification.py in
   full, and ultimate_pipeline/quality/map_hygiene.py::repair_true_zseams (the function actually
   live-wired via stage_08_hygiene.py step 8H-3) in full. Determine precisely: is
   repair_true_zseams algorithmically the same class of approach as the "local seam fixer (F6)"
   F7's evidence describes (a per-seam/local correction, as opposed to F5's whole-graph relaxation),
   or is it a third, different approach? Do not assume -- read both and compare the actual algorithm
   structure (does repair_true_zseams process seams independently/locally, or does it already
   account for the whole connected-component graph like F5 does?).
2. If repair_true_zseams is confirmed to have the same local/per-seam limitation F7 describes for
   junctioned/cyclic topology: reproduce F5's evidence fresh against the CURRENT pinned
   map-of-record (the 20260803 evidence used an older candidate) -- run F5's solver on a COPY,
   never the live pinned file. Report real before/after seam-delta numbers, same shape as the old
   evidence (seams checked, max delta before/after, over-threshold count before/after).
3. Directly compare: run the CURRENTLY-LIVE repair_true_zseams path and F5's solver on the SAME
   starting candidate (a copy), and compare their resulting seam-delta distributions head to head --
   not each against a different baseline. Does F5 measurably outperform the live approach on the
   real map's actual junctioned/cyclic topology (roundabouts, multi-way intersections), or was F7's
   claim specific to a different, older candidate's topology that may not generalize?
4. Confirm F5's own fail-closed checks (slope coefficients preserved, segment counts preserved,
   topology/geometry untouched, seams reduced-or-bounded) still pass on a fresh run against current
   code -- don't just trust the 20260803 evidence is still accurate for the current phase_f5 module.
5. If F5 is confirmed to be both correct and measurably better on real current data: propose (do
   not yet implement, unless the improvement and safety are unambiguous and you have full budget
   remaining) how it would integrate with stage_08_hygiene.py -- does it REPLACE repair_true_zseams,
   run as an additional pass after it, or is there a more nuanced combination? If you do implement
   it, re-run the full offline suite and scripts/measure_candidate_acceptance.py against the pinned
   map before/after and report the diff, and do NOT commit any change to the map-of-record itself in
   this pass -- produce the fix as a reviewable branch only.

End with:
REPAIR_TRUE_ZSEAMS_IS_LOCAL_APPROACH: YES | NO | THIRD_DIFFERENT_APPROACH (explain)
FRESH_F5_REPRODUCTION: <seams checked, max delta before/after, over-threshold before/after>
HEAD_TO_HEAD_COMPARISON: <F5 vs live repair_true_zseams on the same starting candidate>
F5_CHECKS_STILL_PASS: PASS | FAIL
RECOMMENDATION: <integrate now | integrate with caveats | do not integrate, with reasoning>
IMPLEMENTED_THIS_PASS: YES (describe) | NO (why not)
FULL_OFFLINE_TESTS: PASS | FAIL
```
