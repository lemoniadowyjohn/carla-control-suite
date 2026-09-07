# Codex — next batch

## STATUS CHECK FIRST (read before starting anything below)

- **Fix 2** (osm-correspondence-engine-v1-20260907 @ 6889ffdb): verified — kernel sampling and
  grid index both present, 5/5 tests pass. Good.
- **GAP-011** (junction-lanelink-geometry-v1-20260907 @ 179e034f): code change looks reasonable,
  existing 12 tests still pass, but **no test file was touched at all** in that commit. The
  original prompt required: "construct at least one synthetic case where naive [index-order]
  pairing fails and prove your geometry-aware version gets it right." That fixture doesn't exist
  yet. See FOLLOW-UP A below.
- **Fix 1** (connector-pose-validation-v1-20260907 @ 79beecee): **still unresolved, no new
  commit since the fix was requested.** This is the highest-priority item — merging as-is would
  still decertify the current map-of-record (`valid_for_experiments: False` on the real pinned
  map, confirmed earlier). If this is queued and just hasn't been picked up yet, prioritize it
  ahead of everything else below.
- **GAP-009/010** (structure-elevation-v1-20260907): worktree exists but has zero commits beyond
  base -- if this is stalled rather than just not-yet-started, it's queued below as a reminder,
  not a new prompt (the original Wave 2 Prompt 3 text still applies unchanged).

---

## FOLLOW-UP A (do first) — GAP-011 needs its regression fixture

```text
Repository: lemoniadowyjohn/carla-control-suite. Branch: feature/junction-lanelink-geometry-v1-20260907
(continue on this branch, do not start over -- the code change in 179e034f is fine, it's the
missing proof that's the gap).

The original task required: "Regression fixtures: a junction where index-order pairing would be
wrong (e.g. lane cardinality changes across the junction, or one side's lanes are geometrically
reversed relative to sorted |id| order) -- construct at least one synthetic case where naive
pairing fails and prove your geometry-aware version gets it right." No test file was added or
modified in 179e034f (confirmed via `git show 179e034f --stat` -- only
ultimate_pipeline/lanes/lanelink_builder.py changed).

TASK: add that fixture now, in ultimate_pipeline/tests/unit/test_lanelink_builder.py (the
existing 12-test suite for this module) or a new dedicated test file, your choice. It must
concretely demonstrate: given a synthetic junction where sorted-|id|-order pairing would connect
the wrong lanes (construct one where the geometric/heading match disagrees with index order),
the OLD behavior mispairs and the NEW geometry-aware behavior pairs correctly. Show both --
either two tests (one asserting old-would-fail via a stashed/reverted comparison, one asserting
new passes) or one test with an inline comment showing what the naive result would have been.

Also confirm you did the "re-run scripts/measure_candidate_acceptance.py against the pinned
map-of-record before/after" step the original prompt asked for, and report the diff -- this
wasn't in your original commit message either.

End with:
FIXTURE_ADDED: PASS | FAIL
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## FOLLOW-UP B — Wave 2 Prompt 5: Turn-lane and cycle-lane geometric generation (GAP-017, GAP-025)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: lane-count-from-OSM
(feature/lane-count-from-osm-v1-20260907, verified PASS) -- this task extends the same
driving_lane_counts()/ensure_lanes() machinery it just built, do not build a parallel path.
Isolated branch: feature/turn-cycle-lanes-v1-<date>.

CONFIRMED (this session's audit): ultimate_pipeline/enrichment/turn_lanes_writer.py::apply_turn_lanes
only writes a <userData><vector key="turnMarking"/></userData> metadata hint from OSM turn:lanes;
its own docstring states geometry is not modified -- no dedicated left/right-turn <lane> element is
ever created. Separately, lane_generator.py's width table has a "cycleway" entry (2.0m) that is dead
for its apparent purpose: no code path ever emits a type="biking" lane.

TASK:
1. Turn lanes: where OSM turn:lanes indicates a dedicated turn lane at an intersection approach
   (distinct from through-traffic lanes, e.g. "left|through|through|right"), emit it as a real
   additional <lane type="driving"> with appropriate width and the existing turnMarking userData
   hint retained for consumers that read it. Scope this to the approach segment near the junction,
   not the full road length, unless OSM tagging indicates otherwise.
2. Cycle lanes: where OSM tags a genuine dedicated cycleway (cycleway=lane/track, not
   cycleway=shared_lane or a separate cycleway=* way), emit a type="biking" lane using the existing
   2.0m width-table entry.
3. Both must carry the same lane_count_source/confidence/lane_count provenance userData pattern
   feature/lane-count-from-osm-v1-20260907 already established -- do not invent a second provenance
   scheme.
4. Downstream impact: same caution as GAP-001's own prompt -- re-run lanelink_builder's test suite
   and scripts/measure_candidate_acceptance.py against the pinned map before/after, report what
   changed. If a junction's connector-road infrastructure can't represent an added turn/cycle lane
   without breaking, report it as a known limitation rather than silently dropping it.

End with:
TURN_LANES_GEOMETRIC: PASS | FAIL | INCOMPLETE
CYCLE_LANES_GEOMETRIC: PASS | FAIL | INCOMPLETE
PROVENANCE_CONSISTENT: PASS | FAIL
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
```

---

## FOLLOW-UP C — Wave 2 Prompt 6: Lane-count-change gate (GAP-020)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: lane-count-from-OSM
(feature/lane-count-from-osm-v1-20260907, verified PASS) -- this gate is far more meaningful now
that lane counts genuinely vary road-to-road instead of being uniformly 1-per-side. Isolated
branch: feature/lane-count-change-gate-v1-<date>.

CONFIRMED (independently re-verified 2026-09-07): check_lane_section_successors.py's
repair_and_assert_lane_section_successors() repairs mismatched successor/predecessor lane-ID sets
across laneSection boundaries but never reports "lane count changed here" as a quality metric --
it silently repairs to whatever count exists on either side, whether or not that change was
intentional (e.g. matches OSM's own lane-count tapering) or a generation artifact.

TASK: add a new, separate reporting-only check (do not change repair_and_assert_lane_section_
successors' repair behavior) that walks road-to-road links via the existing link graph and flags
any point where driving-lane count changes, with the OSM-derived provenance from GAP-001/019
(lane_count_source userData) attached so a reviewer can distinguish "OSM says this road tapers from
2 to 1 lanes here" (expected) from "generation produced a count mismatch with no OSM basis"
(worth investigating). Wire it into scripts/measure_candidate_acceptance.py as ADVISORY/soft
(metrics + warning), matching this session's established pattern for newly-wired, uncharacterized
checks -- do not hard-fail on day one.

Run it against the pinned map-of-record and report the actual counts by category (OSM-explained
change / unexplained change / no change).

End with:
LANE_COUNT_CHANGE_GATE: PASS | FAIL | INCOMPLETE
PINNED_MAP_FINDINGS: <OSM-explained count>, <unexplained count>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## FOLLOW-UP D — semantic-overlap strict-mode fix (follow-up to GAP-006)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/semantic-overlap-strict-fix-<date>.
Base: feature/semantic-overlap-wiring-20260907 (this continues that work; do not start from main).

CONFIRMED (independent review, 2026-09-07): the GAP-006 wiring commit
(affd2b42, quality_gate_manager.py::gate_semantic_overlap) removed the only call to self.fail()
in that method. Previously, when the heuristic checker (check_semantic_overlap.py) found issues,
self.fail("semantic_overlap", issues) was called, which matters specifically under
UP_STRICT_QUALITY_GATES=1 (quality_gates.py: "if strict_mode and failures: raise ..."). Now,
regardless of whether either checker (heuristic or the new real polygon checker) finds issues,
the method only ever calls self.passed() or logs a "warn" via vreport.add() -- it never calls
self.fail() at all.

Note: UP_STRICT_QUALITY_GATES is not set in any tracked CI config or release profile today, so
this has zero live impact right now -- but it's an undisclosed contract change that should either
be reverted or explicitly documented as intentional, not silently absorbed into a wiring commit.

TASK: decide and implement ONE of:
(a) Restore self.fail("semantic_overlap", issues) for the polygon checker's issues (the real,
    non-heuristic signal) so strict mode's contract still holds, while keeping the map_acceptance.py
    non-fatal/soft behavior for the DEFAULT (non-strict) path exactly as GAP-006 intended.
(b) If soft-only is genuinely the intended new policy even under strict mode, say so explicitly in
    the commit message and in a code comment at the exact line, and add a regression test proving
    strict mode does NOT raise when polygon issues are present (currently untested either way).

End with:
STRICT_MODE_CONTRACT: RESTORED | EXPLICITLY_DOCUMENTED_AS_SOFT
TEST_ADDED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## FOLLOW-UP E — GAP-024 standalone (heading-smoothing re-verification)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/gap-024-heading-smoothing-<date>.

The entrypoints for this experiment exist right now at repo root:
  scripts/regen_experimental_heading_smoothing.py
  scripts/regen_experimental_heading_smoothing_v2_with_recompute.py
Prior reports also exist: reports/post_audit_hardening/C31_HEADING_SMOOTHING_EXPERIMENT_NEGATIVE_RESULT.md,
reports/post_audit_hardening/C33_HEADING_SMOOTHING_V2_RECOMPUTE_STILL_UNSAFE.md. If your worktree's
sparse-checkout doesn't show these, that's a local checkout config issue (this has happened 3+
times already this session with different files) -- do NOT report "artifacts missing" again; run
`git sparse-checkout add scripts reports/post_audit_hardening` (or equivalent) and confirm they
exist before concluding otherwise.

TASK: re-run the full heading-smoothing + geometry-start-recompute experiment
(ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING + ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE,
EXPERIMENTAL_UNSAFE profile only, offline, non-CARLA) against the 2026-09-04 paramPoly3 guard
(commit 21cc6430) to determine whether it actually resolves the previously-documented
410-residual-seam regression, or merely prevents it from silently corrupting data. Document the
result as a dated report (successor to the existing C33 report). This is an EXPERIMENT, not a
production change -- do not enable these flags in any release profile as part of this task.

End with:
GAP-024: PASS | FAIL | INCOMPLETE -- <one-line result>
FULL_OFFLINE_TESTS: PASS | FAIL
```
