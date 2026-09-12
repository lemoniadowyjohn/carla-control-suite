# Codex — PROMPT W: ordinary lane predecessor/successor links — close a real detection gap

## Context (all numbers reproduced directly against the pinned map-of-record:
`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`,
sha256 `2ca342d8...`)

Ordinary (non-junction) lane `<link><predecessor>/<successor>` continuity is NOT derived from OSM
tags by this repo's own code. It comes from the external OSM->SUMO(netconvert)->OpenDRIVE conversion
toolchain, which already encodes real geometric adjacency. Spot-checked 4 of the 1,505 real
lane-count-change boundaries on the pinned map by reconstructing each candidate target lane's world
position (reusing phase_g3_cross_section.py's reconstruct_section, the same technique validated in
this session's G6 adversarial review): all 4 assignments already resolve to the geometrically nearest
candidate lane, 0.0m off, with the non-chosen candidate a full lane-width (3.5m) away. This repo's own
Python code only patches/validates gaps on top of that external output; two mechanisms exist:

1. `ultimate_pipeline/quality/check_lane_section_successors.py` -- ALWAYS live (stage_08_integrity.py,
   unconditional, strict=True), but INTRA-road only (laneSection-to-laneSection within one `<road>`).
   Ran it directly (dry, strict=False) against the pinned map: `repairs=0`, `failures=0` -- its
   `_choose_best_target` ID-proximity heuristic has NEVER fired for real on this map. It is currently
   pure, unexercised insurance.
2. `ultimate_pipeline/fixes/fix_missing_lane_successors.py` -- the only mechanism that touches
   CROSS-road (ordinary road-to-road) lane successor assignment. Disabled by default
   (`UP_AUTOFIX_LANE_SUCCESSORS`, confirmed unset anywhere in tracked config). Ran it directly (dry,
   to a scratch output) against the pinned map: `fixed_count=0`, `fallback_applied=0`,
   `dead_ends_allowed=331` (legitimate road termini, fine) -- its Strategy 1/4 naive
   `successor_lane_id = lane_id` paths, which have a genuine dangling-reference bug (assign a target
   ID with zero check that a lane with that ID exists on the successor road), also never fire on this
   map. It is fully dormant.

**The real, evidenced gap is a missing DETECTOR, not an active corruption.** Directly counted, on the
pinned map: 22,589 ordinary road-to-road boundaries, 9,352 junction-typed boundaries (different
mechanism, out of scope here), 1,505 ordinary boundaries with a driving lane-count/ID-set change, 0
dangling cross-road lane-successor references currently exist. But
`ultimate_pipeline/quality/check_lane_link_targets_exist.py` -- the one gate whose docstring literally
says "predecessor/successor IDs must refer to lanes that exist in the adjacent laneSection" -- only
checks laneSections WITHIN the same road. It has zero cross-road awareness. So if a FUTURE regen
(different OSM extract, different netconvert version, or fix_missing_lane_successors.py ever getting
enabled) ever produces a cross-road dangling lane reference, nothing in this pipeline would catch it
today.

## PROMPT W

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/lane-successor-hardening-v1-<date>.

Reproduce before touching anything: run check_lane_section_successors.repair_and_assert_lane_section_
successors(pinned_map, out_path=None, strict=False) and confirm repairs=0/failures=0; run
fix_missing_lane_successors.fix_missing_lane_successors(pinned_map, scratch_out) and confirm
fixed_count=0/fallback_applied=0/dead_ends_allowed=331. These confirm the two existing repo-owned
lane-successor mechanisms are currently dormant on the map-of-record -- this task is about closing a
detection gap and fixing a latent bug, not fixing an active corruption.

TASK 1 (close the real gap: add cross-road lane-link existence checking): extend
check_lane_link_targets_exist.py (or add a sibling function reusing its Issue dataclass/report shape)
to also validate ordinary road-to-road boundaries: for each road with an elementType="road" `<link>/
<successor>` (and symmetric `<predecessor>`), check that every driving lane's successor/predecessor
target ID in the boundary laneSection actually exists as a lane in the corresponding laneSection of the
linked road (skip junction-typed links -- those are a different mechanism, already covered elsewhere).
Wire it into the same place check_lane_link_targets_exist's existing intra-road check would naturally
run in stage_08_integrity.py (advisory report first is fine, match this codebase's existing
advisory-then-strict convention -- check how the intra-road version is invoked and follow that
pattern). Confirm on the pinned map: 0 issues expected (matching my direct-scan finding of 0 dangling
cross-road refs) -- if you get a nonzero count, treat that as a real finding to investigate, not a bug
in your new checker, and report it explicitly rather than silently adjusting the checker to hide it.

TASK 2 (fix the concrete dormant bug, now that Task 1 gives a safety net to catch it if it recurs):
fix_missing_lane_successors.py's Strategy 1 and Strategy 4 must verify the assumed successor_lane_id
actually exists on the successor road before assigning it; if it doesn't, fall back to a geometric- or
ID-proximity nearest-match (reuse _choose_best_target or equivalent, don't reimplement), and if that
also fails, record still_broken instead of emitting a dangling reference. Add a regression fixture: a
road with 2 driving lanes whose successor road has only 1, proving the old code would have created a
dangling reference (catchable by Task 1's new checker) and the fix does not.

TASK 3 (give the untested intra-road heuristic real coverage): check_lane_section_successors.py's
_choose_best_target has never been exercised on real map data (0 repairs on the pinned map). Add a
synthetic fixture that actually forces it to fire (a road with 2 laneSections where an intra-road
successor link is missing/broken), and while you're touching it, make target selection prefer real
geometric lane-center continuity (reuse phase_g3_cross_section.py's reconstruct_section, same approach
validated in this session's G6 review) over pure ID proximity when they disagree, keeping ID proximity
as the fallback when geometric reconstruction is unavailable. This is hardening for the day this
heuristic is actually needed, not a fix for a currently-observed defect -- say so plainly in your
report, don't oversell it.

Do NOT attempt to change or re-derive the currently-correct cross-road lane links coming from the
conversion toolchain -- they are already geometrically correct per this task's own verification: leave
them alone.

End with:
TASK_1_CROSS_ROAD_DETECTOR: PASS | FAIL -- <issue count found on pinned map, expected 0>
TASK_2_DANGLING_REFERENCE_FIXED: PASS | FAIL
TASK_3_GEOMETRY_AWARE_FALLBACK_ADDED: PASS | FAIL -- <confirm synthetic fixture actually exercises it>
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```
