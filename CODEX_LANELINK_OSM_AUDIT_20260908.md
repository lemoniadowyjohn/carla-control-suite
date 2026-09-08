# Codex — lane-link / OSM-derivation audit findings (2026-09-08)

Requested review: examine lane-link generation and confirm important data is genuinely
OSM-derived, not just geometrically/structurally inferred. Found 3 concrete gaps, all verified
against the real Ingolstadt OSM source
(campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm), not assumed.

## STATUS FIRST: Fix 1 is still the top-priority blocker

feature/connector-pose-validation-v1-20260907 is still at 79beecee -- unchanged since it was
requested. This is the highest-priority open item across everything in flight: merging it as-is
still decertifies the current map-of-record. If Codex has bandwidth, this should be picked up
before any of the 3 new items below. (GAP-016/stage-context-migration is already in progress on
feature/stage-context-migration-v1-20260908 -- that's fine to continue in parallel, just don't let
Fix 1 keep sliding.)

---

## PROMPT I — lanelink_builder.py has zero OSM semantic input (extends GAP-011)

```text
Repository: lemoniadowyjohn/carla-control-suite. Prerequisite: GAP-011's geometry-aware pairing
(feature/junction-lanelink-geometry-v1-20260907) should land first, including its still-pending
regression fixture -- this task builds on top of that work, not instead of it. Isolated branch:
feature/lanelink-turn-restriction-awareness-v1-<date>.

CONFIRMED (2026-09-08): ultimate_pipeline/lanes/lanelink_builder.py::LaneLinkBuilder pairs
incoming-road lanes to connecting-road lanes using ONLY structural signals -- side (left/right),
sign, |id| ordering, and (after GAP-011) geometric/heading match. It never consults any OSM
semantic data about what each lane or connecting road is actually FOR. Confirmed via direct read
of the module (199 lines, no OSM import, no turn-restriction/access parameter anywhere in
regenerate_lane_links's signature or body).

This matters concretely: OSM's turn:lanes tag (and its directional variants, see PROMPT J below)
classifies each lane's real-world turning behavior (e.g. "left|through|through|right" for a
4-lane approach). A left-turn-only lane could currently be geometrically/index-paired to a
straight-through connecting road at a junction where multiple candidate connecting roads exist,
purely because the geometry/index matched, with no check against what OSM says that lane is
actually allowed to do.

TASK:
1. Where an incoming road has OSM turn:lanes (or turn:lanes:forward/backward, see PROMPT J)
   classifying a specific lane's turn category (left/through/right/slight_left/slight_right/
   through;right/etc.), use that classification to VALIDATE candidate connecting-road pairings at
   junctions with multiple connecting roads: does the connecting road's approach direction
   (relative to the incoming road's heading, using the geometry kernel) actually match the lane's
   OSM-tagged turn category? This is a validation/preference layer on top of GAP-011's
   geometry-aware pairing, not a replacement for it -- most junctions have only one valid
   connecting road per lane and this won't change anything there.
2. Where OSM data and geometry disagree (a lane is tagged "left" but the only geometrically-valid
   connecting road goes straight), do not silently pick one -- record BOTH facts (OSM classification
   and the pairing actually made) so it's inspectable, and only escalate to a hard behavior change
   (rejecting a pairing) if you can do so without breaking junctions that currently work correctly.
   Treat this as instrumentation-first: measure how often this disagreement occurs on the real
   pinned map before deciding whether it should ever block a pairing.
3. Add this as metrics/reporting output (e.g. a "lane_link_turn_classification_agreement" field per
   connection), not necessarily a new hard gate -- match the pattern established this session for
   newly-characterized signals (advisory first, hard-gate later once characterized).

Run against the pinned map-of-record and report the actual agreement/disagreement counts.

End with:
TURN_CLASSIFICATION_CONSULTED: PASS | FAIL | INCOMPLETE
PINNED_MAP_AGREEMENT_COUNTS: <agree count>, <disagree count>, <no OSM turn data count>
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT J — turn:lanes:forward/turn:lanes:backward not consumed (352 real occurrences)

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/turn-lanes-directional-v1-<date>
(or fold into feature/turn-cycle-lanes-v1-<date> if that branch -- the already-queued Wave 2
Prompt 5 for GAP-017/025 -- hasn't been dispatched yet; check first, don't duplicate work).

CONFIRMED (2026-09-08): ultimate_pipeline/enrichment/turn_lanes_writer.py::apply_turn_lanes only
reads a generic `turn_lanes` field (sourced from OSM's combined turn:lanes tag). It never reads
turn:lanes:forward or turn:lanes:backward. Counted directly against the real source OSM
(campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm):
turn:lanes:forward appears 199 times, turn:lanes:backward 153 times -- both real, both currently
invisible to this pipeline. OSM uses the directional variants specifically when a bidirectional
road's forward and backward turn-lane patterns differ (the common case for anything but a
one-way street) -- the combined turn:lanes tag is the exception, not the rule, for two-way roads.
Using only the combined tag on a bidirectional road risks either missing real per-direction data
entirely (if only the directional tags are present, which is 352 real cases) or, if some ways
have both combined and directional tags, applying an ambiguous/wrong pattern.

TASK: extend the OSM metadata extraction this pipeline already does for lanes:forward/
lanes:backward (GAP-001's driving_lane_counts(), same pattern) to also extract turn:lanes:forward
and turn:lanes:backward, and wire them into apply_turn_lanes / whatever real geometric turn-lane
generation GAP-017 produces so that forward-direction lanes get the forward-tagged pattern and
backward-direction lanes get the backward-tagged pattern, falling back to the combined turn:lanes
tag only when neither directional variant is present (matching the existing fallback hierarchy
pattern this codebase already uses for lane counts and widths -- exact tag > directional split >
combined > inferred > fallback).

Add a regression fixture: a road with turn:lanes:forward="left|through" and
turn:lanes:backward="through|right" (deliberately different per direction) and confirm each
direction's lanes get their own correct pattern, not the same pattern applied to both.

End with:
DIRECTIONAL_TURN_LANES: PASS | FAIL | INCOMPLETE
FIXTURE_ADDED: PASS | FAIL
FULL_OFFLINE_TESTS: PASS | FAIL
```

---

## PROMPT K — road/lane access restrictions (psv/access/motor_vehicle/bicycle) never carried into XODR

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/osm-access-restrictions-v1-<date>.

CONFIRMED (2026-09-08): zero files anywhere in ultimate_pipeline/ reference OSM's access,
psv, motor_vehicle, or bicycle tags (grep across the whole tree, tests included, returned no
matches). These are real, frequent tags in the source data: access (2016 occurrences), psv (2777),
bicycle (2308), motor_vehicle (324), vehicle (134) -- none of this access-restriction semantic
data survives into the generated XODR in any form (no userData, no lane/road attribute, nothing).

This is a road/lane CLASSIFICATION gap, not a geometry gap: a road OSM tags as psv=yes (public
service vehicles / buses only, or with special PSV access) or access=private or motor_vehicle=no
(e.g. a cycle-only or pedestrian-only way that happens to carry some other qualifying tag)
currently produces XODR output with no distinguishing signal from an ordinary fully-public
drivable road.

TASK (investigate before implementing -- confirm the actual real-world impact first):
1. Determine which of these tags, if any, currently causes a road to be WRONGLY generated as a
   normal drivable road when it should be excluded or restricted (i.e., is there an existing
   upstream filter -- in whatever decides highway class / whether to emit a road at all -- that
   already handles access=private/motor_vehicle=no correctly, just without a downstream
   traceability signal? Or does a private/restricted way currently get treated identically to a
   public one?). This determines whether this is a CORRECTNESS bug (wrong roads being generated
   as public) or a METADATA gap (roads are correct, but the restriction isn't recorded).
2. If it's a metadata gap only: add access-restriction data as XODR userData on the relevant
   road/lane elements (source, value, confidence -- same provenance pattern as GAP-001/019),
   advisory only, no behavior change.
3. If it's a correctness bug (roads that should be excluded/restricted are being generated as
   ordinary drivable roads): that's a more significant finding -- report it clearly with concrete
   examples (way IDs, tag values, what was generated) before proposing a fix, since changing which
   roads get generated at all is a bigger decision than adding metadata.

Report actual counts from the pinned map: how many generated roads/lanes correspond to an OSM way
carrying one of these restriction tags, and what (if anything) currently distinguishes them in the
output.

End with:
INVESTIGATION_RESULT: CORRECTNESS_BUG_FOUND | METADATA_GAP_ONLY | NO_ISSUE_FOUND
METADATA_ADDED: PASS | FAIL | NOT_APPLICABLE
PINNED_MAP_RESTRICTED_ROAD_COUNT: <count>
FULL_OFFLINE_TESTS: PASS | FAIL
```
