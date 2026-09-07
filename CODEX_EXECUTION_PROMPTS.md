# Codex Execution Prompts

Each prompt below is self-contained and ready to hand to Codex directly. Send them in the order
listed within each wave; waves can run in parallel with each other where noted. Every prompt follows
this repo's established governance pattern: verify source authority first, work on an isolated
branch, never touch `submission/`/frozen evidence/the map-of-record pin, produce evidence, end with a
verdict block.

Full context for every gap ID cited: `MAP_QUALITY_GAP_REGISTER.json` on this branch
(`architecture/production-map-quality-20260906`).

---

## WAVE 1, PROMPT 1 — Canonical geometry-primitive evaluator (GAP-037, GAP-035)

```text
Repository: lemoniadowyjohn/carla-control-suite

Verify remote authority before anything else:
  git remote -v
  git ls-remote origin refs/heads/stabilize/research-release-20260905
Confirm your local base matches the remote tip exactly. If it does not, STOP and report
BLOCKED_SOURCE_AUTHORITY rather than substituting a different SHA.

Create an isolated branch: feature/geometry-kernel-v1-<date>
Do not touch the primary checkout. Do not start CARLA. Do not modify the map-of-record pin
(ultimate_pipeline/carla_tools/map_registry.py) or anything under submission/, campaigns/,
reports/post_audit_hardening/.

CONFIRMED BUG (independently verified, not a guess): ultimate_pipeline/geometry/geometry_validator.py
line ~230 backfills a missing geometry element's x/y using
    dx = math.cos(h) * prev["length"]; dy = math.sin(h) * prev["length"]
unconditionally, regardless of the PREVIOUS geometry primitive's type. This formula is only correct
if the previous primitive is a `line`. For `arc`, `spiral`, or `paramPoly3`, this produces a wrong
position.

BROADER FINDING (well-corroborated, not yet exhaustively scoped): this codebase has at least 3
independent, partial implementations of OpenDRIVE geometry-primitive evaluation:
  1. ultimate_pipeline/geometry/geometry_validator.py (the buggy one above)
  2. ultimate_pipeline/topology/roundabout_v2/core.py::sample_road (handles line/arc/paramPoly3/poly3,
     built this session, reasonably complete but not shared with anything else)
  3. ultimate_pipeline/enrichment/crosswalk_writer.py's curve-aware road matcher
  4. ultimate_pipeline/enrichment/structure_classifier.py's sampler (reported, not yet confirmed by
     Claude, to approximate spiral/poly3 as straight-line segments -- confirm this yourself first)

TASK: build ONE canonical geometry-primitive evaluator module (suggest:
ultimate_pipeline/geometry/opendrive_geometry_kernel.py) supporting line, arc, spiral/clothoid, poly3,
paramPoly3, with at minimum:
  - pose_at_s(geometry, s) -> (x, y, heading)
  - heading_at_s, curvature_at_s
  - endpoint(geometry) -> (x, y, heading)
  - sample(geometry, spacing) -> list of poses
  - bounding_box(geometry)
  - project_point(geometry, x, y) -> (s, lateral_offset, distance)  # for correspondence/matching use
For spiral/clothoid: use a mathematically valid Fresnel-integral evaluation or a numerically
well-conditioned deterministic approximation with an explicitly tested and documented error bound.
Do NOT fall back to a straight-line approximation for any primitive type -- if you cannot evaluate a
primitive exactly, that is a stop condition, not a license to approximate silently.

Build a test oracle FIRST (TDD): analytic fixtures for line, quarter-circle, half-circle,
constant-curvature arc, a clothoid transition, poly3, paramPoly3 (both pRange=normalized and
pRange=arcLength). For each, hand-derive (not implementation-derived) expected start/mid/end pose,
heading, curvature, bounding box, and point-projection results with explicit numerical tolerances.

Then migrate ONE consumer at a time, starting with geometry_validator.py's backfill bug (delete the
unsafe dx/dy formula, replace with a call to the new kernel's endpoint()/pose_at_s()). Do not big-bang
migrate all 4 consumers in one commit -- one consumer per commit, full test suite green after each,
so a regression is attributable to a specific migration step.

Required outputs: the kernel module + its test oracle, geometry_validator.py's bug fixed and migrated,
a GEOMETRY_KERNEL_VERIFICATION.md documenting the oracle's fixtures and tolerances, and a report on
whether crosswalk_writer.py/structure_classifier.py/roundabout_v2/core.py should migrate too (you do
not need to migrate them in this pass -- confirming the plan is enough).

Full pytest must stay green. No threshold weakening. No test deletion to make a regression
disappear.

Stop and report if: source authority cannot be proven, a spiral/clothoid case cannot be evaluated to
a rigorously justified tolerance, or migrating geometry_validator.py's backfill logic changes output
on the CURRENT pinned map-of-record in a way you cannot explain (re-run
scripts/measure_candidate_acceptance.py against the pinned file before and after your change and
diff the reports -- do not just trust that tests pass).

End with:
GEOMETRY_KERNEL: PASS | FAIL | INCOMPLETE
CONSUMERS_MIGRATED: <list>
CONSUMERS_NOT_YET_MIGRATED: <list, with reason>
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
Claude will independently review before this merges. Do not merge it yourself.
```

---

## WAVE 1, PROMPT 2 — Lane count from OSM (GAP-001)

```text
Repository: lemoniadowyjohn/carla-control-suite. Verify source authority the same way as the previous
prompt before starting. Isolated branch: feature/lane-count-from-osm-v1-<date>. No CARLA, no
map-of-record mutation, no submission/ changes.

CONFIRMED (this session's own audit): ultimate_pipeline/enrichment/lane_generator.py::ensure_lanes
always creates exactly one driving lane per side (left id=1, right id=-1) for every non-junction
road, regardless of OSM lane-count tags. ultimate_pipeline/enrichment/lane_width_policy.py DOES parse
OSM lanes=/lanes:forward/lanes:backward (via _lane_count_from_meta) but only uses the parsed count as
a divisor for width-per-lane -- never to decide how many <lane> elements to emit.

TASK: make lane COUNT genuinely OSM-derived, with the same kind of tiered fallback lane_width_policy.py
already has for width (exact OSM tag -> inferred -> fallback), and attach provenance to each generated
lane (source: osm:lanes / osm:lanes:forward+backward / inferred / fallback; confidence: 0.0-1.0).
Emit this provenance both in a LANE_PROVENANCE_REPORT.json AND as XML userData on the lane element
itself (not just an out-of-band JSON report -- a consumer reading the XODR file alone should be able
to tell where a lane's count/width came from).

Handle the downstream consequences deliberately, do not just add lanes and hope: junction lane-link
generation (ultimate_pipeline/lanes/lanelink_builder.py) currently pairs lanes by sorted |id| order
and WILL be affected by roads suddenly having more lanes than before -- re-run its test suite and the
map-of-record acceptance gates after your change and report what changed, do not assume it's fine.

If a genuinely multi-lane road's downstream junction-connector infrastructure cannot represent the
added lane count without breaking (e.g. the connector road on the other side of a junction still has
only 1 lane), do not silently drop the extra lanes or silently mismatch counts -- this is exactly the
class of defect this session's audit already found (27 isolated lane components, LANELINK_DEFECT).
Report it as a known limitation rather than papering over it.

Required tests: a fixture road with lanes=3/lanes:forward=2/lanes:backward=1 produces the correct
lane count and IDs. Full existing lane-generation and lane-link test suites must stay green.

End with:
LANE_COUNT_FROM_OSM: PASS | FAIL | INCOMPLETE
PROVENANCE_ATTACHED: PASS | FAIL
DOWNSTREAM_IMPACT: <summary of what changed in lane-link/junction/acceptance gates, or "no measurable
  impact">
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
Claude will independently review before this merges.
```

---

## WAVE 1, PROMPT 3 — sidewalk=no fix (GAP-036, small, standalone)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/sidewalk-no-fix-<date>.
No CARLA, no map-of-record mutation.

CONFIRMED BUG: ultimate_pipeline/enrichment/sidewalk_builder.py lines ~175-187, the hint branching
(`if hint == "both": ... elif hint == "left": ... elif hint == "right": ... elif default_both_sides:
...`) has no explicit case for hint == "no" -- it falls through to the default_both_sides branch,
meaning an OSM road explicitly tagged sidewalk=no still gets sidewalks added (unless it's also a
motorway/trunk-class road).

TASK: add the missing branch (`elif hint == "no": continue` or equivalent) so an explicit sidewalk=no
tag is always honored, with a regression test proving it. Also check whether _get_osm_sidewalk_hint
correctly parses OSM's other sidewalk conventions (sidewalk:left=no combined with sidewalk:right=yes,
sidewalk=separate) -- if these aren't handled, add them if cheap, otherwise document as a known
limitation rather than silently mishandling them.

This is small and isolated -- do not scope-creep into a full sidewalk-model rewrite in this prompt.

End with:
SIDEWALK_NO_FIX: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## WAVE 1, PROMPT 4 — Confirm-then-fix batch (GAP-038, GAP-039, GAP-040, GAP-041, GAP-042)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/confirm-then-fix-batch-<date>.
No CARLA, no map-of-record mutation.

These 5 findings came from an external analysis and were NOT independently verified by Claude this
session (unlike GAP-035/GAP-036, which were spot-checked and confirmed). Your first job for EACH one
is to confirm or refute it against the actual current code, before deciding whether to fix it. Do not
assume any of them are real just because they're in the gap register -- treat each as a hypothesis.

1. GAP-038 (lane width flattening): check whether lane_width_policy.py's repair path really writes
   a=target,b=0,c=0,d=0 unconditionally, replacing any existing width polynomial regardless of
   whether the original was valid. If real: change the repair to only replace genuinely invalid
   widths (missing/nonfinite/impossible/negative), preserving a valid existing polynomial untouched.

2. GAP-039 (graph ID collision risk): check ultimate_pipeline/quality/map_hygiene.py's
   quarantine_island_roads() adjacency-graph construction for whether road and junction IDs share an
   unprefixed string keyspace. If real: prefix node keys (e.g. "road:123" vs "junction:123") so they
   cannot collide. Cheap fix if confirmed.

3. GAP-040 (signal validation not scoped to road): check
   ultimate_pipeline/enrichment/traffic_light_infer.py::validate_signal_references() -- does it check
   lane-ID existence anywhere in the whole map, or specifically on the signal's own road/laneSection?
   If it's global: scope the check to the specific road/laneSection at the signal's own s-position.

4. GAP-041 (DEM lenient override bypasses release profile): check whether
   UP_ELEVATION_FALLBACK_POLICY=lenient can weaken elevation fallback behavior under a
   production-oriented RELEASE_PROFILE. If real: apply the same pattern settings.py already uses for
   the ENABLE_UNSAFE_* geometry flags (lines ~372-402) -- fail closed / ignore the lenient override
   under any profile except DEVELOPMENT/EXPERIMENTAL_UNSAFE.

5. GAP-042 (tiling bounds cache keyed only by road ID): check the tiler's _BOUNDS_CACHE (or
   equivalent) for whether it's scoped only by road ID, risking stale results across different maps
   sharing a road ID in the same process. If real: scope the cache key by map identity/geometry hash
   in addition to road ID.

For each of the 5: report CONFIRMED or REFUTED with the specific evidence (file:line, or "searched
and did not find this pattern"), before implementing anything. If REFUTED, do not implement a fix --
update the gap register entry's status to REFUTED with your evidence instead. If CONFIRMED, implement
the fix with a regression test.

End with, for each of the 5:
GAP-0XX: CONFIRMED | REFUTED -- <one-line evidence>
  FIX_STATUS (if confirmed): PASS | FAIL | INCOMPLETE
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## WAVE 1, PROMPT 5 — Roundabout V2 finalization (GAP-032, GAP-033, GAP-034)

```text
Repository: lemoniadowyjohn/carla-control-suite. Work on the EXISTING branch
feature/roundabout-reconstruction-v2-20260907 (do not create a new branch -- this continues that
work). Read CLAUDE_INDEPENDENT_REVIEW_ROUNDABOUT_V2.md on that branch first for full context.

Three fixes, all small and well-scoped by the independent review:

1. GAP-032: ultimate_pipeline/topology/roundabout_v2/core.py::validate_lane_mapping unconditionally
   rejects any -1->-1 lane mapping as an invalid "sentinel", but
   ultimate_pipeline/topology/roundabout_v2/lane_links.py::map_lanes (the function actually used in
   the real reconstruction path) correctly treats a real -1->-1 mapping as valid. Resolve the
   contradiction: either retire validate_lane_mapping if it's genuinely superseded by
   lane_links.validate_links, or rename it to make its narrower purpose explicit (it appears to exist
   specifically to reject V1's old universal -1/-1 fallback pattern, which is a different, narrower
   concept than "is this specific mapping valid"). Update __init__.py's __all__ and the test suite
   accordingly. Do not leave both exported with contradictory semantics.

2. GAP-033: add the two undisclosed scope simplifications to known_limitations (in
   docs/map_quality/ROUNDABOUT_RECONSTRUCTION_V2.md and/or the evidence JSON schema): hardcoded 3.5m
   lane width in ring.py (not reusing lane_width_policy.py's OSM-derived hierarchy), and the
   zero-grade Hermite elevation boundary condition in ring.py (not reading the source road's true
   grade at each anchor). You do not need to FIX either of these in this pass, just document them
   honestly.

3. GAP-034: CODEX_ROUNDABOUT_V2_EVIDENCE.json and ROUNDABOUT_V2_BASELINE.json contain verified-wrong
   numbers (claimed "39 passed" for the legacy roundabout tests, actual is 44; claimed "5825
   collected" in one file vs "5830" in another, actual is 5830). Regenerate both evidence files with
   the correct, freshly-re-run numbers. Do not hand-edit the numbers -- re-run the actual test
   commands and capture real output, so the fix itself is verifiable.

End with:
API_CONTRADICTION_RESOLVED: PASS | FAIL
KNOWN_LIMITATIONS_UPDATED: PASS | FAIL
EVIDENCE_CORRECTED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## WAVE 2 — send only after Wave 1's geometry kernel and lane-count prompts report PASS

## WAVE 2, PROMPT 1 — Connector pose validation + boundary-offset gate (GAP-002, GAP-004)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: Wave 1's geometry-kernel branch must
be merged/available first -- use its pose_at_s/endpoint functions, do not reimplement pose evaluation
again. Isolated branch: feature/connector-pose-validation-v1-<date>.

CONFIRMED (this session's audit): ultimate_pipeline/topology/junction_connector_rebuild.py::
ConnectorValidator.validate() has its lane-section and attachment-pose checks explicitly commented
out with "SKIP for now". Separately, a fresh measurement against the pinned map-of-record found
20.3% of junction-connector road-boundary links (9,176 of 45,178) have a geometric offset >=0.05m
from their connected road's true endpoint, with a MEDIAN offset of exactly one lane-width (3.5m) --
and this is structurally invisible to the acceptance gate because
ultimate_pipeline/quality/check_geometric_continuity.py deliberately routes junction-connector links
into a separate, non-gating bucket.

TASK:
1. Implement the two disabled checks in ConnectorValidator (lane-section existence/validity,
   attachment-pose match against the connected road's true endpoint position AND heading using the
   canonical geometry kernel).
2. Add tangent (heading) continuity checking at connector seams -- currently only position continuity
   is checked anywhere.
3. Wire the 20.3%-offset measurement into an actual gate (not just a diagnostic), using the 10
   worst-offset roads already identified (69981, 69984, 69987, 68258, 69384, 69597, 69111, 69919,
   69815, 69917) as your regression fixtures.
4. Do NOT attempt to "fix" every one of the 20.3% of offset roads in this pass -- that's likely a
   separate, larger remediation. This prompt is about making the defect VISIBLE and VALIDATED, not
   necessarily eliminating every instance immediately. If you do find a clean, low-risk fix for the
   root cause (e.g. connector reference-lines anchored to the wrong lane-boundary/index), implement
   it; if it looks larger/riskier, report the root cause precisely and stop there.

Re-run scripts/measure_candidate_acceptance.py against the pinned map-of-record before and after your
change and report the diff -- do not just trust unit tests.

End with:
CONNECTOR_VALIDATOR_CHECKS: PASS | FAIL | INCOMPLETE
BOUNDARY_OFFSET_GATE: PASS | FAIL | INCOMPLETE
OFFSET_ROOT_CAUSE: <found and fixed | found, not fixed (explain why) | not conclusively found>
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary>
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
```

## WAVE 2, PROMPT 2 — Spatial OSM<->XODR correspondence engine (GAP-005)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: Wave 1's geometry kernel. Isolated
branch: feature/osm-correspondence-engine-v1-<date>.

CONFIRMED (this session's audit): ultimate_pipeline/enrichment/osm_meta_index.py matches OSM data to
XODR roads by street NAME only -- a pure dict keyed by road name, no spatial component. Position-
specific metadata (turn:lanes via turn_lanes_writer.py, regulatory signs via
regulatory_sign_writer.py) gets propagated through this name-only match in the LIVE pipeline path
(both are called unconditionally from stage_04_enrichment.py), with no confidence scoring and no
ambiguity handling -- a value scoped to one intersection approach in OSM can be silently applied to
every XODR segment sharing that street name.

POSITIVE REFERENCE IMPLEMENTATION ALREADY IN THIS CODEBASE:
ultimate_pipeline/enrichment/crosswalk_writer.py does genuine geometric correspondence (real
footway=crossing node geometry, curve-aware nearest-point matching using a spatial grid index, 5m
threshold, explicit rejection when no road is within range). Use this as your template, not a
from-scratch design.

TASK: build one shared OSM<->XODR correspondence module. For every association, emit:
{"osm_way_id": ..., "xodr_road_id": ..., "confidence": 0.0-1.0, "class": "EXACT|HIGH|AMBIGUOUS|UNMATCHED",
"evidence": {"centerline_overlap": ..., "mean_distance_m": ..., "heading_error_deg": ...,
"name_match": bool, "road_class_match": bool, ...}}. Scoring dimensions: spatial overlap/distance,
heading, road name, highway class, oneway direction, lane count (once GAP-001 lands), topological
neighborhood. AMBIGUOUS associations must be skipped with a recorded reason, never silently resolved
to the first/best candidate.

Migrate turn_lanes_writer.py and regulatory_sign_writer.py to consume this engine (requiring at least
HIGH confidence for position-specific data; name-only matching remains acceptable ONLY for genuinely
street-level attributes, not per-approach/per-segment data).

Produce OSM_XODR_CORRESPONDENCE_REPORT.json with the full association set and confidence-class
breakdown for the pinned map.

End with:
CORRESPONDENCE_ENGINE: PASS | FAIL | INCOMPLETE
TURN_LANES_MIGRATED: PASS | FAIL
REGULATORY_SIGNS_MIGRATED: PASS | FAIL
AMBIGUOUS_ASSOCIATION_COUNT: <integer, against the pinned map>
FULL_OFFLINE_TESTS: PASS | FAIL
```

## WAVE 2, PROMPT 3 — Bridge/tunnel deck-height model (GAP-009, GAP-010)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: Wave 1's geometry kernel (structure
classification's sampler is one of the fragmented geometry-evaluation sites -- migrate it as part of
this task if not already done by Wave 1). Isolated branch: feature/structure-elevation-v1-<date>.

CONFIRMED (this session's audit): the "deck_linear" elevation policy for bridge/tunnel-classified
roads (ultimate_pipeline/enrichment/elevation_importer.py, matches commit e3f91dbc) still samples the
SAME ground-terrain DEM at the road's two endpoints and linearly interpolates -- there is no
independent deck-height/clearance data source anywhere in the module, and no check that an endpoint
sample represents "top of abutment" rather than "ground beneath the abutment". No minimum
bridge-deck-to-ground-separation threshold exists anywhere, and tunnels get identical treatment to
bridges despite needing the opposite validation (below-terrain, not above).

TASK: add a plausibility check comparing a structure-classified road's interpolated elevation against
the surrounding terrain DEM along its length (not just at the two endpoints) -- flag (do not
necessarily auto-correct) cases where a "bridge" road's elevation doesn't stay meaningfully above
terrain, or a "tunnel" road's elevation doesn't stay meaningfully below. Add explicit, configurable
thresholds for minimum deck-to-ground separation and tunnel overburden depth, enforced the same way
existing elevation gates (grade, seam, smoothness) already are. If a genuine independent
deck-height/clearance data source is not available from OSM tags, scope this down to a plausibility
CHECK rather than a full replacement model, and say so explicitly rather than fabricating a height
value.

End with:
STRUCTURE_ELEVATION_CHECK: PASS | FAIL | INCOMPLETE
THRESHOLDS_ADDED: <list>
PINNED_MAP_STRUCTURE_FLAGS: <count of bridges/tunnels flagged as implausible, or "none found">
FULL_OFFLINE_TESTS: PASS | FAIL
```

## WAVE 2, PROMPT 4 — Junction lane-link geometry-awareness (GAP-011)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: Wave 1's geometry kernel
(feature/geometry-kernel-v1-20260907, verified PASS 2026-09-07) and lane-count-from-OSM
(feature/lane-count-from-osm-v1-20260907, verified PASS 2026-09-07) should both be available --
this task gets more consequential once roads can genuinely have >1 lane per side. Isolated branch:
feature/junction-lanelink-geometry-v1-<date>.

CONFIRMED (independently re-verified 2026-09-07): ultimate_pipeline/lanes/lanelink_builder.py::
LaneLinkBuilder.regenerate_lane_links pairs lanes purely by sign and |id| ordering via a nested
match_by_direction() helper (positive-to-positive, negative-to-negative, inner-first) -- no
geometry or heading input at all. The module's own validation entrypoint,
sanitize_junction_lane_links(), is a confirmed hardcoded stub:
    """Stub for laneLink sanity check."""
    print(f"   [INFO] LaneLink Sanity Check: {label} (STUB)")
    return {"status": "ok", "summary_metrics": {}}
It always reports "ok" regardless of input, so there is currently no independent check that would
catch a mispairing even if one existed.

TASK:
1. Extend match_by_direction (or replace it) to use the geometry kernel's pose_at_s/endpoint to
   compare each candidate lane pair's actual centerline position and heading at the junction seam,
   not just sign+|id| order. Where index-order and geometry agree, keep the fast path; where they
   disagree, prefer geometry and record the disagreement (this is a real signal that GAP-011 exists
   in the input, worth surfacing even if you can't fix the input road itself in this pass).
2. Implement sanitize_junction_lane_links() for real: verify every generated lane link's endpoints
   are geometrically coincident (within a documented tolerance) and headings are continuous, using
   the same kernel. Return real summary_metrics (counts of checked/passed/failed links), not the
   hardcoded stub.
3. Regression fixtures: a junction where index-order pairing would be wrong (e.g. lane cardinality
   changes across the junction, or one side's lanes are geometrically reversed relative to sorted
   |id| order) -- construct at least one synthetic case where naive pairing fails and prove your
   geometry-aware version gets it right.

Re-run scripts/measure_candidate_acceptance.py against the pinned map-of-record before and after;
report the diff. This module runs on every regen, so a subtle behavior change here is high-blast-
radius -- do not merge without full offline tests green and the acceptance diff explained.

End with:
GEOMETRY_AWARE_PAIRING: PASS | FAIL | INCOMPLETE
SANITIZE_STUB_REPLACED: PASS | FAIL
MISPAIRING_FIXTURE_PROVEN: PASS | FAIL
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
```

## WAVE 2, PROMPT 5 — Turn-lane and cycle-lane geometric generation (GAP-017, GAP-025)

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

## WAVE 2, PROMPT 6 — Lane-count-change gate (GAP-020)

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

## WAVE 3 — send only after Wave 2's correspondence engine (GAP-005) reports PASS

## WAVE 3, PROMPT 1 — Regulatory signs, signal/speed-limit precedence, turn restrictions (GAP-005 extension, GAP-040)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: Wave 2's OSM<->XODR correspondence
engine (feature/osm-correspondence-engine-v1-<date>) must be merged/available -- this task consumes
its confidence-scored association output directly, do not re-derive matching logic. Isolated
branch: feature/regulatory-precedence-v1-<date>.

Re-verify against the merged correspondence engine's actual output schema before starting (do not
assume the schema sketched in the Wave 2 prompt is exactly what shipped).

TASK:
1. Migrate remaining position-specific OSM consumers (regulatory sign placement beyond what GAP-005
   already migrated, if any remain; speed-limit tags; turn-restriction relations) to require at
   least HIGH confidence from the correspondence engine, same bar as turn_lanes_writer.py/
   regulatory_sign_writer.py from Wave 2.
2. Define and implement explicit source-of-truth precedence where multiple signals could apply to
   the same road/lane (e.g. an explicit OSM maxspeed tag vs. a highway-class-based default; an
   explicit stop/give_way relation vs. inferred junction-priority logic) -- document the precedence
   rule, do not leave it as implementation-order-dependent.
3. GAP-040 follow-up: the confirm-then-fix batch (feature/confirm-then-fix-batch-20260907) already
   scoped signal-lane-reference validation to the signal's own road/laneSection. Confirm that fix's
   test coverage extends to a MULTI-laneSection road with a signal reference at a non-zero s (the
   existing test only covers a single-section road) -- add that fixture if missing.

End with:
REGULATORY_MIGRATION: PASS | FAIL | INCOMPLETE
PRECEDENCE_RULE_DOCUMENTED: PASS | FAIL
GAP_040_MULTISECTION_COVERAGE: PASS | FAIL | ALREADY_ADEQUATE
FULL_OFFLINE_TESTS: PASS | FAIL
```

## WAVE 3, PROMPT 2 — OSM-vs-generated semantic completeness metric (GAP-014)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: Wave 2's correspondence engine is the
clean way to do this precisely, but a coarser name/area-scoped version could start earlier if you
want to unblock this independently -- your call, note which approach you took. Isolated branch:
feature/osm-completeness-metric-v1-<date>.

CONFIRMED (this session's audit): map_acceptance.py::_enrichment_completeness_counts only checks
generated counts are non-zero (fails only if functional_signals_count<=0 AND
traffic_light_object_count<=0) -- no comparison against how many traffic_signals/crossing/etc tags
exist in the source OSM for the same area.

TASK: add a completeness metric comparing source OSM counts (traffic_signals, crossings, stop/
give_way, speed limits, turn restrictions -- whatever categories the correspondence engine already
classifies) against generated object counts for the same area, reported as a ratio per category.
Wire as ADVISORY metrics in map_acceptance.py's report, not a hard fail (no baseline "expected"
ratio has been established yet). Run against the pinned map-of-record and report the actual ratios.

End with:
COMPLETENESS_METRIC: PASS | FAIL | INCOMPLETE
APPROACH_USED: correspondence_engine | name_scoped_coarse
PINNED_MAP_RATIOS: <per-category ratio summary>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## WAVE 4 — housekeeping, can run any time, low risk

## WAVE 4, PROMPT 1 — Dead-code wiring swap: semantic overlap (GAP-006)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/semantic-overlap-wiring-<date>.

CONFIRMED (this session's audit): two classes both named SemanticOverlapChecker exist.
ultimate_pipeline/quality/check_semantic_overlap.py::validate() is wired live via
quality_gate_manager.py::gate_semantic_overlap but is a weak heuristic (only checks whether a road has
BOTH a sidewalk-type and building-type object attached to the same road element -- no actual geometry).
ultimate_pipeline/quality/semantic_overlap.py::check() is a REAL Shapely polygon-intersection
implementation, confirmed via repo-wide grep to be imported nowhere.

TASK: switch quality_gate_manager.py::gate_semantic_overlap to call the real polygon-intersection
implementation instead of the heuristic. Run it against the pinned map-of-record and report how many
findings it produces (this gate is currently deliberately soft/non-fatal per map_acceptance.py's own
documented rationale -- do not change that without a separate, explicit decision; just report the
numbers so a future decision can be made with real data). Keep both implementations running in
parallel (log both results) for one full regen cycle before removing the old heuristic, so a
before/after comparison exists. Only after that comparison is reviewed should the old heuristic
function be considered a genuine deprecation candidate for OpenCode.

End with:
REAL_IMPLEMENTATION_WIRED: PASS | FAIL
FINDINGS_ON_PINNED_MAP: <count>
COMPARISON_LOGGED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

## WAVE 4, PROMPT 1B — Restore strict-mode fail() for semantic_overlap (follow-up to GAP-006)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/semantic-overlap-strict-fix-<date>.
Base: feature/semantic-overlap-wiring-20260907 (this continues that work; do not start from main).

CONFIRMED (independent review, 2026-09-07): the GAP-006 wiring commit
(affd2b42, quality_gate_manager.py::gate_semantic_overlap) removed the only call to self.fail()
in that method. Previously, when the heuristic checker (check_semantic_overlap.py) found issues,
self.fail("semantic_overlap", issues) was called, which matters specifically under
UP_STRICT_QUALITY_GATES=1 (quality_gates.py: "if strict_mode and failures: raise ...").
Now, regardless of whether either checker (heuristic or the new real polygon checker) finds
issues, the method only ever calls self.passed() or logs a "warn" via vreport.add() -- it never
calls self.fail() at all. This means strict mode's "any gate failure raises" contract is silently
untestable for semantic_overlap specifically, in both directions (neither checker can trigger it
anymore).

Note: UP_STRICT_QUALITY_GATES is not set in any tracked CI config or release profile today, so
this has zero live impact right now -- but it's an undisclosed contract change that should either
be reverted or explicitly documented as an intentional policy change, not silently absorbed into
a wiring commit.

TASK: decide and implement ONE of:
(a) Restore self.fail("semantic_overlap", issues) for the polygon checker's issues (the real,
    non-heuristic signal) so strict mode's contract still holds, while keeping the map_acceptance.py
    non-fatal/soft behavior for the DEFAULT (non-strict) path exactly as GAP-006 intended.
(b) If soft-only is genuinely the intended new policy even under strict mode, say so explicitly in
    the commit message and in a code comment at the exact line, and add a regression test proving
    strict mode does NOT raise when polygon issues are present (currently untested either way).

Either choice is acceptable -- what is not acceptable is leaving it undocumented and untested.

End with:
STRICT_MODE_CONTRACT: RESTORED | EXPLICITLY_DOCUMENTED_AS_SOFT
TEST_ADDED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## WAVE 4, PROMPT 2B — GAP-024 standalone (heading-smoothing re-verification)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/gap-024-heading-smoothing-<date>.
GAP-021/022/023 from the original Wave 4 Prompt 2 batch are already done (GAP-021 by Codex on
feature/quality-gate-fixes-20260907 @8b12cc47; GAP-022/023 by Claude directly on the same branch
@cb82079f, both independently verified). Only GAP-024 remains open from that batch.

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

---

## WAVE 4, PROMPT 2 — Small fixes batch (GAP-021, GAP-022, GAP-023, GAP-024)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/quality-gate-fixes-<date>.
Four small, independent fixes -- one commit each, full tests green after each:

1. GAP-021: add predecessor/successor consistency and duplicate/conflicting-connection detection to
   ultimate_pipeline/quality/check_junction_integrity.py's JunctionIntegrityGate.

2. GAP-022: fix structure_scanner.py's elevation-anomaly check, which currently requires >=2
   elevation records per road to fire but every road on the current pinned map has exactly 1 (this
   generator's single-polynomial-per-road encoding) -- it unconditionally reports zero anomalies as a
   result, not because elevation is smooth. Compare across road-to-road links instead of within-road,
   or otherwise make the check actually able to fire against this pipeline's real output shape.

3. GAP-023: fix structure_scanner.py's curvature-anomaly estimate, which divides a heading delta by
   segment length and can be inflated by near-zero-length microsegments (confirmed: road 51979's
   top-ranked "anomaly" is a 1.4cm segment, not a real sharp turn). Apply a minimum segment-length
   floor before computing the ratio.

4. GAP-024: re-run the full heading-smoothing + geometry-start-recompute experiment
   (ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING + ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE, EXPERIMENTAL_UNSAFE
   profile only, offline, non-CARLA) against the 2026-09-04 paramPoly3 guard (commit 21cc6430) to
   determine whether it actually resolves the previously-documented 410-residual-seam regression, or
   merely prevents it from silently corrupting data. Document the result as a dated report (successor
   to the existing C33 report). This is an EXPERIMENT, not a production change -- do not enable these
   flags in any release profile as part of this task.

End with, for each of the 4:
GAP-0XX: PASS | FAIL | INCOMPLETE -- <one-line result>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## General rules for every prompt above (do not repeat back to me, just follow them)

- Verify source/remote authority before any mutation, every time -- do not assume a previous prompt's
  verification still holds if meaningful time has passed.
- Never start CARLA, never call CARLA RPC, never touch `submission/`, `campaigns/` (except reading),
  `reports/post_audit_hardening/` (except reading), or the map-of-record pin in `map_registry.py`.
- Work on an isolated branch/worktree, never the primary checkout.
- Full offline pytest must stay green after every commit. No threshold weakening, no test deletion to
  hide a regression, no updating an expected hash solely because behavior changed.
- Produce real evidence (re-run actual commands, capture real output) rather than hand-authored
  evidence JSON -- this session's own review caught a wrong self-reported test count (GAP-034)
  precisely because it was hand-transcribed rather than freshly captured.
- Claude independently reviews every branch before it merges. Do not merge your own work.
