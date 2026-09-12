# Codex — PROMPT Y: characterize + fix G3's 751 "coverage INCOMPLETE" sample failures

## Context

`feature/g3-cross-section-coverage-v1-20260912` correctly fixed a real honesty bug: G3 previously
passed silently even when cross-sections couldn't be reconstructed; it now fails closed
(`coverage_status: INCOMPLETE`, `g3_verdict: PHASE_G_CROSS_SECTION_INCOMPLETE`) when 751 non-stub
sections return `reconstruct_section(...) -> {"ok": False}`. That fix is correct and should stand.

I characterized the 751 directly against the pinned map-of-record (sha256 `2ca342d8...`) by running
`audit_full_map` myself and cross-referencing each affected road's declared `<road length=...>`
against the true sum of its `_road_geometry_segments()` lengths. Checked all 200 entries surfaced in
`bad_roads` (the full 751 is truncated to 200 in the evidence JSON's report list, but every single one
of the 200 I checked follows the identical pattern):

- **Every one has `declared_length - geometry_segment_sum` = exactly 0.001000m (1mm), no exceptions.**
- **Every one has exactly ONE unavailable sample, always at `s == declared_length`** (the very last
  boundary sample, never mid-road).
- `validate_section_samples` samples up to `s = road_length` inclusive; when actual geometry coverage
  falls 1mm short of the declared length, that final sample point lands just past the last real
  segment, `_pose_at` returns `x=None`, and `reconstruct_section` reports `ok=False`.

This is very likely a sub-millimeter rounding artifact in whatever wrote `length` (rounds/truncates
independently from the geometry segments' own lengths), not a real geometric defect -- 1mm is well
below any driving-relevant tolerance. But I have NOT verified the root cause (why 1mm, why so
consistent, which upstream stage writes `length` this way), and I only checked 200 of 751 -- verify
the rest, don't assume they're identical without checking.

## PROMPT Y

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/g3-length-epsilon-v1-<date>.
Base your work on feature/g3-cross-section-coverage-v1-20260912 (the branch that added the
fail-closed INCOMPLETE verdict) -- do not undo that fix, refine it.

TASK 1 (verify, don't assume): re-run phase_g3_cross_section.audit_full_map against the pinned
map-of-record and check ALL 751 non-stub-unavailable sections (not just the 200 I sampled) for the
declared-length-vs-geometry-segment-sum gap and the "always exactly one sample, always at s ==
declared_length" pattern. Report the real distribution -- if any of the 751 DON'T fit this pattern
(a different gap size, a mid-road occurrence, multiple samples per road), treat those as a separate,
still-open finding and do not silently fold them into the epsilon fix below.

TASK 2 (root cause, don't just patch the symptom): determine why these roads' declared `length`
differs from their true geometry-segment-sum by ~1mm. Check whichever pipeline stage writes/finalizes
`<road length=...>` (likely stage_05_geometry.py or the OpenDRIVE serialization layer) against
whatever computes/writes the geometry segments themselves -- is `length` computed from a
higher-precision intermediate value that gets rounded/truncated differently than the segments when
serialized? Report the exact mechanism if you find it. If the true root cause requires touching a
widely-used serialization path, do not do so in this pass unless you're confident it's safe --
characterizing it clearly is an acceptable outcome on its own.

TASK 3 (fix the sampler's edge tolerance): validate_section_samples / reconstruct_section should not
report "unavailable" for a sub-millimeter sampling overrun at a road's declared end -- this is a
sampling artifact, not a coverage gap. Add a small, explicit epsilon tolerance (justify the exact
value from your Task 1 data -- e.g. if every real case is ~1mm, something like 5-10mm gives headroom
without masking real defects) so that sampling `s` values within the tolerance of the road's actual
geometry coverage are clamped to the last valid position instead of failing. Critically: this must
NOT silently swallow a genuinely large coverage gap -- add a regression fixture proving a road with a
real 1-meter (or larger) declared-length/geometry mismatch still correctly reports "unavailable" and
still fails the gate. Re-run the full audit after the fix and report the new `non_stub_unavailable_
section_count` (expect it to drop to 0 if Task 1 confirms all 751 fit the sub-mm pattern, or to the
residual count of genuinely-different cases if some don't).

End with:
TASK_1_FULL_751_CHARACTERIZATION: <breakdown, e.g. "751/751 fit the 1mm/end-of-road pattern" or
  "N fit, M do not, described as: ...">
TASK_2_ROOT_CAUSE: <found mechanism, or "not determined, documented as open">
TASK_3_EPSILON_FIX: PASS | FAIL -- new non_stub_unavailable_section_count: <before> -> <after>
REGRESSION_FIXTURE_FOR_REAL_GAPS: PASS | FAIL (must still fail closed on a genuine large gap)
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```
