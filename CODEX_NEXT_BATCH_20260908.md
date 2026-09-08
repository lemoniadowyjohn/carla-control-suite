# Codex — next batch (2026-09-08)

## Verified this session

- **Fix 1 RESOLVED and independently verified** (b53af3cd): `gate_geometric_continuity()`
  reverted to its safe default; new `gate_junction_connector_boundary_alignment()` correctly
  scoped and unwired from live orchestration. Confirmed directly against the real pinned
  map-of-record: default path `ok=True`, explicit gate `ok=False` with all 9176 issues still
  surfaced. New regression test at the QualityGateManager level (not just the raw function)
  passes. This branch is now trustworthy to merge whenever the operator is ready.
- **Stage-context-migration (GAP-016) on track** — step 1 of 5 landed correctly (new
  `StageContext` dataclass alongside the old dict, verified as a complete/faithful schema match).

## Still pending, no progress since last check

- **GAP-011's regression fixture** (feature/junction-lanelink-geometry-v1-20260907) — still not
  added. The code change (179e034f) is fine; the required proof it actually beats naive pairing
  is still missing. See Follow-up A below (unchanged from before).

## PROMPT L — merged: turn-lane geometric generation + directional turn:lanes (GAP-017, GAP-025, + new finding)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: lane-count-from-OSM
(feature/lane-count-from-osm-v1-20260907, verified PASS). Isolated branch:
feature/turn-cycle-lanes-v1-<date>. This merges two previously-separate prompt drafts into one
task since neither has been dispatched yet and both touch the same files -- do this as one
coherent piece of work, not two passes.

CONFIRMED (this session's audit):
1. ultimate_pipeline/enrichment/turn_lanes_writer.py::apply_turn_lanes only writes a
   <userData><vector key="turnMarking"/></userData> metadata hint from OSM turn:lanes; its own
   docstring states geometry is not modified -- no dedicated left/right-turn <lane> element is
   ever created.
2. It also only reads the generic combined turn:lanes tag -- never turn:lanes:forward or
   turn:lanes:backward. Counted directly against the real source OSM
   (campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm):
   turn:lanes:forward appears 199 times, turn:lanes:backward 153 times, both currently invisible
   to this pipeline. The directional variants are the norm for a bidirectional road with
   different forward/backward turn patterns -- the combined tag is the exception.
3. Separately, lane_generator.py's width table has a "cycleway" entry (2.0m) that is dead for its
   apparent purpose: no code path ever emits a type="biking" lane.

TASK:
1. Turn lanes: where OSM turn:lanes (or its directional variants) indicates a dedicated turn lane
   at an intersection approach (distinct from through-traffic lanes, e.g.
   "left|through|through|right"), emit it as a real additional <lane type="driving"> with
   appropriate width and the existing turnMarking userData hint retained. Scope to the approach
   segment near the junction unless OSM tagging indicates otherwise.
2. Directional correctness: extract turn:lanes:forward and turn:lanes:backward using the same
   metadata-extraction pattern already established for lanes:forward/lanes:backward (GAP-001's
   driving_lane_counts()). Forward-direction lanes get the forward-tagged pattern, backward get
   the backward-tagged pattern. Fall back to the combined turn:lanes tag only when neither
   directional variant is present -- exact tag > directional split > combined > inferred >
   fallback, matching this codebase's existing hierarchy pattern for lane counts/widths.
3. Cycle lanes: where OSM tags a genuine dedicated cycleway (cycleway=lane/track, not
   cycleway=shared_lane or a separate cycleway=* way), emit a type="biking" lane using the
   existing 2.0m width-table entry.
4. All new lanes carry the same lane_count_source/confidence/lane_count provenance userData
   pattern GAP-001 already established -- do not invent a second scheme.
5. Regression fixtures required: (a) a road with turn:lanes:forward="left|through" and
   turn:lanes:backward="through|right" (deliberately different per direction) proving each
   direction gets its own correct pattern, not the same pattern applied to both; (b) a fixture
   proving a genuine turn lane becomes real geometry, not just a userData hint.
6. Downstream impact: re-run lanelink_builder's test suite and scripts/measure_candidate_acceptance.py
   against the pinned map before/after, report what changed. If a junction's connector-road
   infrastructure can't represent an added turn/cycle lane without breaking, report it as a known
   limitation rather than silently dropping it.

End with:
TURN_LANES_GEOMETRIC: PASS | FAIL | INCOMPLETE
DIRECTIONAL_TURN_LANES: PASS | FAIL | INCOMPLETE
CYCLE_LANES_GEOMETRIC: PASS | FAIL | INCOMPLETE
PROVENANCE_CONSISTENT: PASS | FAIL
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
FIRST_BLOCKER: <one exact blocker or NONE>
```

---

## Priority order for everything else already drafted and committed on this branch

Not re-pasted here since the full text is already committed and unchanged -- send in this order:

1. **Follow-up A** (`CODEX_NEXT_BATCH_20260907.md`) — GAP-011 regression fixture. Still the
   oldest outstanding item.
2. **PROMPT K** (`CODEX_LANELINK_OSM_AUDIT_20260908.md`) — OSM access-restrictions investigation
   (psv/access/motor_vehicle/bicycle). No dependencies, can run any time.
3. **PROMPT I** (`CODEX_LANELINK_OSM_AUDIT_20260908.md`) — lanelink turn-restriction awareness.
   Depends on GAP-011's fixture landing first (item 1 above).
4. **Follow-up C** (`CODEX_NEXT_BATCH_20260907.md`) — lane-count-change gate (GAP-020).
5. **Follow-up D** (`CODEX_NEXT_BATCH_20260907.md`) — semantic-overlap strict-mode fix.
6. **Follow-up E** (`CODEX_NEXT_BATCH_20260907.md`) — GAP-024 heading-smoothing re-verification.
7. **PROMPT F** (`CODEX_GAP018_013_20260907.md`) — GAP-018 tangent reversal on road 45622.
8. **PROMPT G** (`CODEX_GAP018_013_20260907.md`) — GAP-013 Phase J visual QA wiring.
9. **Wave 3 Prompt 2** (`CODEX_EXECUTION_PROMPTS.md`) — GAP-014 completeness metric. Unblocked
   (its prerequisite, the OSM correspondence engine, landed and was verified).
10. **Wave 3 Prompt 1** (`CODEX_EXECUTION_PROMPTS.md`) — regulatory precedence. Also unblocked,
    but re-read its own instruction to verify against the correspondence engine's actual shipped
    schema before sending, since it may need a light edit.
