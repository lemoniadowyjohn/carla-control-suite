# Codex — PROMPT HH: cross-validate XODR road-level successor/predecessor topology against OSM way adjacency

## Context

This session established, and re-confirmed by direct grep (`grep -rli "osm.*successor\|osm.*predecessor" ultimate_pipeline --include=*.py`, zero matches outside this new prompt's own future work), that **no existing module cross-validates XODR road-level `<link><predecessor>/<successor>` topology against OSM way connectivity**. What exists today, precisely:

- `ultimate_pipeline/lanes/lanelink_builder.py` — builds junction laneLinks from pure XODR geometry (lane widths/positions), zero OSM references. This is correct and should stay geometry-only; not in scope to change.
- `ultimate_pipeline/quality/check_lane_link_targets_exist.py` — validates that a lane's predecessor/successor target ID *exists* in the adjacent laneSection. Existence only, not a semantic/source check.
- `ultimate_pipeline/quality/check_lane_section_successors.py` — repairs missing intra-road lane links.
- `ultimate_pipeline/tools/audit_lane_link_turn_classification.py` — cross-checks OSM `turn:lanes` tag semantics against geometrically-built junction laneLinks (this session, commit `46e1cacd`). This is about **turn-marking semantics at junctions**, not general road-to-road connectivity — different question.

None of these ask "does XODR road A's declared successor/predecessor actually correspond to the road OSM's own way-node topology says should be next." OSM ways carry real connectivity: two ways sharing an endpoint `<nd ref="...">` are topologically connected in the source data. This prompt builds that missing cross-check.

Reusable infrastructure already proven this session (`ultimate_pipeline/enrichment/osm_xodr_correspondence.py`):
- `MatchResult` (`osm_way_id`, `xodr_road_id`, `confidence`, `match_class` — EXACT/HIGH/etc.)
- `build_metadata_associations()` — the same high-confidence-only correspondence engine already live in `stage_04_enrichment.py`
- `_osm_direction(way_points, road_points)` — returns `"forward"`/`"reverse"`/`None`: whether the OSM way's node order runs the same way as the XODR road's increasing-s direction. **This is the key piece for this task** — it tells you which physical end of the OSM way (first node vs. last node) corresponds to the XODR road's predecessor-end (s=0) vs. successor-end (s=length), which you need to correctly compare "OSM way's shared node" against "XODR road's successor/predecessor," not just assume node order matches s order.

## PROMPT HH

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912 at
or after 95840497. Isolated branch: feature/osm-road-link-topology-crosscheck-v1-<date>.

TASK 1: build an OSM way-adjacency index from the real pinned source
(campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm): for every pair of
highway ways sharing an endpoint node (first or last <nd ref>), record which ends are shared. Report
real numbers: how many highway ways exist, how many adjacency edges you find, and the degree
distribution (most nodes should be degree 2, junctions/intersections higher) -- sanity-check this
against something you can verify independently (e.g. does the junction-degree distribution look like a
real street network, not degenerate).

TASK 2: for every XODR road with an EXACT/HIGH-confidence correspondence to an OSM way (reuse
build_metadata_associations() -- do not build a parallel, less-rigorous matching scheme), use
_osm_direction() to determine which physical end of the OSM way maps to the road's predecessor-end vs
successor-end. Then check: does the adjacent OSM way (from Task 1's index) at that end ALSO have a
high-confidence XODR correspondence, and if so, does ITS xodr_road_id match what the road's own
<link><predecessor>/<successor> actually declares (directly, or reachable through a junction whose
connections plausibly route to it -- a road-to-road OSM adjacency often becomes a road-to-junction-to-
road XODR chain, not always a direct link)? Design and justify exactly how you resolve the junction case
before writing the check -- this is the part most likely to need real judgment, not a mechanical
translation.

TASK 3: run this against the real pinned map/OSM pair (a COPY, per this session's established
convention -- read-only for this task, no mutation). Report real numbers: how many road-link boundaries
have a high-confidence OSM cross-check available at all (most won't -- both endpoints need a
high-confidence correspondence), how many agree, how many disagree, and for a representative sample of
disagreements, show the actual OSM way ids / XODR road ids / declared vs. expected topology so a human
can sanity-check whether a disagreement is a real defect or a correspondence-engine limitation (e.g. a
many-to-one OSM-way-to-XODR-road split that this task's adjacency logic doesn't yet handle). Do not
assume disagreements are defects -- characterize them the same honest way DD characterized its FAIL
population (near-miss vs. dramatic, real cause vs. measurement artifact) before drawing a conclusion.

TASK 4: wire this as a new, clearly-named advisory-only checker (does not repair anything, does not gate
pipeline pass/fail on its own -- matching turn_restriction_audit's own precedent exactly), recording
results via self.vreport the same way stage_04_enrichment.py already does for the turn-classification
audit. Only wire it live if Task 3's signal-to-noise (agree/disagree/no-data breakdown) is actually
useful -- if the high-confidence-correspondence coverage turns out too sparse to produce a meaningful
number of checkable boundaries, say so honestly and describe what threshold or matching improvement
would be needed, rather than wiring a check that fires on almost nothing.

TASK 5: run the full offline test suite. Confirm whether your worktree is sparse or non-sparse (this
session found a sparse `!**/*.xodr` pattern made a genuinely 0-failure branch look like it had 27
failures -- state which you're running). Do not promote anything to auto_map_of_record, do not mutate
the pinned map or OSM source.

End with:
TASK_1_OSM_ADJACENCY_INDEX: <way count, edge count, degree distribution sanity>
TASK_2_CROSSCHECK_DESIGN: <junction-case resolution strategy, with reasoning>
TASK_3_REAL_MAP_RESULTS: <checkable boundaries>/<total>, agree/disagree counts, disagreement characterization
TASK_4_WIRING_DECISION: WIRED (advisory) | NOT_WIRED (with the specific reason)
TASK_5_FULL_OFFLINE_TESTS: PASS | FAIL -- <sparse or non-sparse, confirmed>
MAP_OF_RECORD_MUTATED: NO
```
