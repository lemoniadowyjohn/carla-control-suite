# Byte-level determinism secondary sources — investigation (2026-08-28)

## Task
Thesis Chapter 9 future-work item #13: "Byte-level determinism root cause (secondary
sources beyond the timestamp fix)". Investigate what, besides the already-fixed
`<header date="...">` / leading-comment timestamp, varies byte-for-byte between two
Osm2Odr runs on identical pinned inputs.

## Step 0: checked for prior work first
Before doing any new work, searched `reports/post_audit_hardening/` for existing
determinism/byte-level reports, per this session's standing discipline. Found
`THESIS_ITEM13_BYTE_DETERMINISM_SECONDARY_SOURCES_RESOLVED.md`, already committed at
`af7dd86b` ("fix(determinism): resolve thesis future-work #13 -- no secondary
byte-nondeterminism sources"), already present on this branch's history (an ancestor of
current HEAD). **This exact task has already been done in a prior session pass.**

Rather than duplicate it or fabricate new "findings," this report (a) independently
re-derives the prior claim from raw bytes (not just trusting the earlier report's
prose), and (b) explicitly follows up on the one honest scope gap that report itself
flagged, to see whether it can be closed cheaply.

## Independent re-verification (fresh evidence, not copied from the prior report)

Re-ran the byte-diff analysis myself, from scratch, directly against the same real
artifacts still present on disk (`reports/post_audit_hardening/C15_RQ4_DR/determinism/
run_00{0,1,2}.xodr`, gitignored via `*.xodr` but present locally — 3 real repeated
Osm2Odr conversions of the same pinned OSM input, 83,433,072 bytes each):

```
sizes: 83433072 83433072 (run_000 vs run_001, matches run_002 too)
run_000 vs run_001: 6 differing byte offsets total: [75, 77, 78, 1750, 1752, 1753]
run_000 vs run_002: 6 differing byte offsets total: [75, 77, 78, 1750, 1752, 1753]
run_001 vs run_002: 4 differing byte offsets total: [77, 78, 1752, 1753]
```

Context around offset 75 (bytes 15..155):
```
1.0" encoding="UTF-8"?>\r\n\r\n<!-- generated on 2026-08-20 15:11:28 by \r\n<configuration ...
                                                          ^^ this is offset 75 (minute digit)
```
run_001's same region reads `15:12:10` instead of `15:11:28` — i.e. offsets 75/77/78 are
the `MM` and `SS` digits of the wall-clock minute/second in the leading XML comment.

Context around offset 1750 (bytes 1700..1820), identical prefix across all 3 runs:
```
r="4" name="" version="1.00" date="Thu Aug 20 15:11:28 2026" north="5472743.54" ...
                                    ^^^^^ offsets 1750/1752/1753 = same MM:SS digits,
                                          inside the <header date="..."> attribute
```

**Out of 83,433,072 bytes per file, at most 6 byte positions ever differ, and every one
of them falls inside the minute/second digits of the two already-known timestamp
locations.** The bbox attributes (`north`/`south`/`east`/`west`) immediately adjacent to
the second timestamp are untouched. No other byte anywhere in the file differs. This is
a stronger, offset-level form of the prior report's line-level diff and it agrees with it
exactly — same two locations, no new source found.

Also re-ran the existing regression test independently:
```
tests/unit/test_exp_osm_to_xodr_determinism_normalized.py — 5 passed
```
including `test_real_c15_determinism_runs_are_raw_nonidentical_but_timestamp_normalized_identical`,
which asserts 3 distinct raw sha256 but exactly 1 normalized sha256 across the same real
artifacts. Confirmed passing, unchanged, on current HEAD (`7ddcc926`, which contains
`af7dd86b`). No code under `ultimate_pipeline/osm/osm_to_xodr_wrapper.py` or
`exp_osm_to_xodr_determinism.py` has changed since that commit
(`git log af7dd86b..HEAD` on those paths is empty).

**Verdict: the prior finding stands, confirmed by an independent re-derivation. At the
raw Osm2Odr conversion stage, the timestamp (2 locations, ≤6 bytes) is still the only
source of byte-level nondeterminism.** None of candidate sources (a) float-accumulation-
order, (b) dict/set-iteration-driven XML attribute/element reordering, (c) an additional
embedded timestamp/UUID, or (e) locale-dependent float formatting are present — a
reordering or formatting difference would necessarily shift byte offsets or file length
across a much larger span than 6 fixed positions, and the file sizes are identical
(83,433,072 bytes, all 3 runs).

## Following up on the prior report's honest scope gap

The prior report explicitly flagged what it did NOT check:

> "This is verified at the Osm2Odr raw-seed-conversion stage using 3 already-produced
> real runs — it was not re-verified against a fresh full-pipeline (post-enrichment)
> multi-run, which would require an expensive new regen cycle... that inference is not
> independently re-verified end-to-end in this pass."

Per this task's methodology (no live CARLA, no expensive regen without a cheap fixture),
I checked whether a cheap fixture-scale reproduction of the *post-enrichment* path
exists:

```
grep -rl "exp_osm_to_xodr_determinism\|test_deterministic_alignment" tests/  -> only the
  existing test_exp_osm_to_xodr_determinism_normalized.py itself (raw-stage only)
grep -r "deterministic_alignment|check_osm_to_carla_determinism|compare_runs_determinism" tests/
  -> no matches
```

No cheap fixture exercising post-enrichment multi-run byte determinism exists. Per the
task's explicit instruction not to attempt an expensive full regen for this
investigation, I did not run one. Instead, as a bounded, offline, static check, I
confirmed the *mechanism* claim the prior report relied on ("every downstream enrichment
stage operates deterministically on that same structural input... no mechanism by which a
new secondary source would appear"):

```
grep -rn "datetime.now|time.time()|uuid.uuid4|utcnow" ultimate_pipeline/enrichment/ ultimate_pipeline/osm/
```
Two files use wall-clock calls (`blender_runner.py`, `osm2world_runner.py`), but only to
populate `result.start_time` / `result.end_time` / `result.duration_sec` on in-memory
run-result objects (job telemetry), not written into the `.xodr` file.

```
grep -rl "\.xodr" ultimate_pipeline/enrichment/
```
4 hits (`collision_lod_policy.py`, `coordinate_control.py`, `realism.py`,
`traffic_light_infer.py`) — all *read* the xodr for reference geometry when generating
OSM2World/Blender mesh outputs (OBJ/FBX); none of them re-serialize or rewrite the
`.xodr` file itself post-Osm2Odr.

This supports (but, consistent with the prior report's own honesty standard, does not
fully substitute for an end-to-end regen of) the inference that no enrichment stage
introduces new byte-level variation into the `.xodr` artifact specifically. **This
remains the one open, named gap**: nothing currently disproves it, but it has still only
been checked statically, not via a second live post-enrichment regen. Closing it fully
would require running the canonical regen entrypoint (per `C11_reproducibility_and_
governance.md`) twice end-to-end and diffing every artifact, not just the `.xodr` —
which is an expensive live-pipeline operation this task's methodology explicitly
disallows without a cheaper existing fixture, and none exists yet.

## No code changes made

No fix was needed or attempted:
- The one real, previously-open question (secondary sources at the Osm2Odr stage) was
  already closed and committed (`af7dd86b`) in a prior pass; this investigation
  independently reconfirms it from raw bytes rather than trusting the prior report's
  prose, and finds nothing further to fix at that stage.
- The remaining scope gap (full post-enrichment multi-run) is not closable within this
  task's offline/no-expensive-regen constraints, and is not a "safely fixable narrow
  bug" in the sense item 4 of the task's investigation approach asks for — it's a
  missing piece of *verification*, not a known defect. Fabricating a fix for an
  unconfirmed defect would violate this session's TDD discipline (no RED test exists to
  drive a fix, because no fixture exists to produce one cheaply).

## What would be needed to fully close this (out of scope here)
1. A cheap, small OSM fixture (not full Ingolstadt) that still exercises every
   enrichment stage end-to-end, so a 2x full-pipeline regen is affordable in CI/local
   dev — does not currently exist per the `tests/` search above.
2. Run the canonical regen entrypoint twice on that fixture and diff every artifact
   (xodr + OBJ/FBX + any generated metadata/report JSON that gets hashed for
   reproducibility), not just the xodr.
3. If a cheap fixture is judged not worth building, the alternative is one expensive,
   explicitly-authorized full Ingolstadt double-regen — out of scope for this task per
   its own instructions.

## Summary
This exact investigation (thesis future-work item #13, byte-level determinism secondary
sources) was already completed and committed in a prior session pass (`af7dd86b`,
2026-08-27): the only byte-level source of Osm2Odr non-determinism on identical inputs is
the wall-clock timestamp, written in exactly two places (`<!-- generated on ... -->`
comment and `<header date="...">`), already normalized-away by `_normalize_timestamps` /
`_sha256_normalized_text` in `exp_osm_to_xodr_determinism.py`, with a passing regression
test (`tests/unit/test_exp_osm_to_xodr_determinism_normalized.py`, 5/5 tests) asserting
this directly against real C15 evidence.

This pass independently re-derived that finding from raw bytes rather than trusting the
existing report: diffed the same 3 real 83MB `.xodr` runs byte-for-byte myself and found
at most 6 differing byte offsets total (out of 83,433,072), every one inside the
minute/second digits of the same two known timestamp locations — no new source, same
conclusion, stronger evidence (offset-level, not just line-level). Re-ran the existing
test suite for this area: 5/5 passed, unchanged since the prior commit.

No code changes were made — none were needed. The one legitimate remaining gap is
verification-only (full post-enrichment multi-run byte diff), explicitly out of reach
under this task's no-expensive-regen constraint since no cheap fixture exists yet; static
review of the enrichment stages (no wall-clock writes into `.xodr`, no stage rewrites the
xodr post-Osm2Odr) is consistent with — but does not fully prove — the existing inference
that no new secondary source appears downstream.
