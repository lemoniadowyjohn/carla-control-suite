# Codex — PROMPT FF: make roundabout_v2 actually apply its RECONSTRUCT_GEOMETRY candidates

## Context

Your own PROMPT EE work (`feature/roundabout-v2-source-aware-detection-v1-20260913`, merged into
`integration/session-batch1-20260912` at `e23b84ca`) built `source_aware.py` and wired it into
`detect_candidates(root, osm_path=...)` (`core.py:106-110` calls
`source_aware.detect_osm_spatial_candidates` and extends the existing marker/arc-or-spiral candidate
list with the new `OSM_SPATIAL` ones). Real-map result: 97/135 OSM roundabouts now produce a candidate,
correctly classified into `action_counts: {"PRESERVED_VALID": 90, "PRESERVE_ORIGINAL": 4,
"RECONSTRUCT_GEOMETRY": 3}`. Your own report correctly declined to wire this because
`RoundaboutV2Reconstructor.reconstruct_transactional()` "only clones and diagnoses the root; it does
not apply a reconstruction."

Read `reconstructor.py` yourself to confirm this is still accurate (don't trust this summary without
checking), but as of this session, the gap is narrower than "V2 can't materialize anything" --
`reconstruct_ring_transactional()` (`reconstructor.py:43-73`) already exists, already builds real
segment roads (`build_segment_specs` + `build_segment_roads` from `ring.py`), already validates them
(`validate_segmented_ring`), and already applies them to a deep-copied root transactionally (commits
the clone only if validation passes, returns the original root unmodified otherwise, raises on an id
collision rather than silently overwriting). It is simply never CALLED from
`reconstruct_transactional()`, which only runs `analyze()` (diagnosis) and returns the clone unmodified
regardless of what each `RoundaboutModel.action` says:

```python
def reconstruct_transactional(self, root, *, osm_path=None, candidates=None):
    clone = copy.deepcopy(root); diagnostics = []
    for model in self.analyze(clone, osm_path=osm_path, candidates=candidates):
        diagnostics.append({...})  # <-- action is recorded here, never acted on
    return clone, diagnostics
```

## PROMPT FF

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912 at
or after e23b84ca (has your EE source-aware detection already merged). Isolated branch:
feature/roundabout-v2-materialization-v1-<date>.

TASK 1: read reconstructor.py, ring.py, core.py, and validator.py in full to confirm the exact current
call graph (don't assume the summary above is complete -- verify from the code). Confirm specifically:
what does extract_endpoint_anchors() need (junction element + ring_road_ids) to produce the anchors
reconstruct_ring_transactional() requires, and does a RoundaboutModel already carry everything needed
(model.anchors, model.candidate.junction_ids, model.candidate.road_ids) to call it directly, or is
something missing (e.g. a real first_road_id allocation strategy that doesn't collide with existing
road ids on a 32k+-road map)?

TASK 2: extend reconstruct_transactional() (or add a clearly-named companion method if you decide
reconstruct_transactional's contract should stay diagnostic-only and a new method should own
application -- your call, justify it) so that, for every RoundaboutModel whose action is
RECONSTRUCT_GEOMETRY, it actually calls the ring-building path with that model's own anchors and a safe
first_road_id (must not collide with any existing road id in the map -- verify your allocation strategy
against the real map's actual id space, not an assumption about it), and folds the result into ONE
final clone. Models with any other action (PRESERVED_VALID, PRESERVE_ORIGINAL, REJECT_AMBIGUOUS) must
leave their roads/junctions completely untouched in the final clone -- this is the majority case (90/97
on the real map), so the common path must be a true no-op, not a rebuild-and-compare-equal.
Transactional at the WHOLE-MAP level: if reconstructing ANY one RECONSTRUCT_GEOMETRY candidate fails
validation, that specific candidate must fall back to leaving its original geometry untouched (matching
reconstruct_ring_transactional's own PRESERVE_ORIGINAL fallback), not abort the entire operation --
confirm and preserve this per-candidate isolation, don't accidentally make one failure block all 96
others.

TASK 3: run this against a COPY of the real pinned map-of-record (never the pinned file itself), with
the real OSM source, exactly reproducing your own EE detection (97 candidates, same 3
RECONSTRUCT_GEOMETRY ones). Report: how many of the 3 RECONSTRUCT_GEOMETRY candidates actually get
applied vs. fall back to PRESERVE_ORIGINAL after validation, and why for any that fall back. Diff the
output XODR against the input: confirm road/junction counts changed by EXACTLY the expected amount (new
segment roads for applied candidates, zero unrelated changes elsewhere), byte-identical elsewhere.

TASK 4: NOW run the before/after acceptance comparison CC and EE could not run (no modified candidate
existed yet): scripts/measure_candidate_acceptance.py on the original map vs. this actually-modified
copy, full metric diff, not just roundabout-specific numbers. This is the real test of whether
materialization is safe, not just "did it produce output."

TASK 5: investigate wiring into the live pipeline using this session's established convention
(env-var gated, default off, transactional, persisted JSON report, never a hard pipeline-fail on its
own -- see UP_ENABLE_JUNCTION_CONNECTOR_SNAP / UP_ENABLE_G6_LANE_COVERAGE_REPAIR). Wire it ONLY if Task
3/4 are clean (correct application count, zero unexpected structural changes, no acceptance-metric
regressions). If anything is off, do NOT wire it -- report exactly what's wrong instead, the same honest
disposition your own BB/CC/DD/EE work has already modeled every time.

TASK 6: run the full offline test suite. IMPORTANT: verify your suite run isn't undercounting due to a
sparse checkout -- this session found its own C:-drive worktree's `!**/*.xodr` sparse-checkout pattern
was silently excluding real fixture files, making a fully-green branch (5865 passed, 0 failed on a full
non-sparse checkout) look like it had 27 pre-existing failures. Confirm your own worktree is either
non-sparse or has the fixtures your specific new tests need, and say which. Do not promote anything to
auto_map_of_record.

End with:
TASK_1_CALL_GRAPH_CONFIRMED: <what's actually needed vs. what a RoundaboutModel already carries>
TASK_2_MATERIALIZATION_BUILT: PASS | FAIL -- <design summary, especially the id-allocation strategy>
TASK_3_REAL_MAP_APPLICATION_RESULTS: <applied>/<3> RECONSTRUCT_GEOMETRY candidates, fallback reasons for any that didn't apply
TASK_4_ACCEPTANCE_DELTA: <full metric diff>
TASK_5_WIRING_DECISION: WIRED (advisory, default off) | NOT_WIRED (with the specific reason)
TASK_6_FULL_OFFLINE_TESTS: PASS | FAIL -- <sparse or non-sparse, confirmed>
MAP_OF_RECORD_MUTATED: NO
```
