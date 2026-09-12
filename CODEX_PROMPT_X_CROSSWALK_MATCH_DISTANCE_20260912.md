# Codex — PROMPT X: recover 18 real crosswalks silently dropped by a fixed 5m match threshold

## Context (reproduced directly against the pinned map-of-record + pinned OSM source:
`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`,
`campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`)

`ultimate_pipeline/enrichment/crosswalk_writer.py` matches each OSM `footway=crossing` way to the
nearest road within `DEFAULT_MAX_MATCH_DIST_M = 5.0` (a fixed constant, not derived from road width).
Ran `extract_osm_crossings` + `match_crossing_to_road` directly: 127/179 (71%) match, 52 don't.
Widened the search to find each unmatched crossing's TRUE nearest road regardless of threshold:

- **18 are near-misses, 5.01m-14.53m from their true nearest road** -- one is literally 0.01m over
  the cutoff. Checked all 18 for ambiguity risk (brute-force top-3 nearest roads): every one either
  has a clear, healthy gap to the 2nd-nearest candidate (0.19m-3.3m), or the top-2 are two directional
  carriageways of the same divided road at virtually identical distance (gap <0.001m -- e.g. way
  815412593 vs roads 46356/47247) where either attachment is equally correct. **None show a
  plausible wrong-road false match.** Raising the threshold to rescue these is evidenced-safe, not a
  guess.
- **32 are far misses, 16.67m-41.81m away.** Spot-checked 3 (ways 954049852, 1028458468,
  1183958168) -- coordinates land inside the map area but nowhere near a road; not yet characterized
  whether these are legitimately out of scope (e.g. crossings over footways/cycleways with no
  corresponding OpenDRIVE road) or point to a real road-network coverage gap. Investigate before
  deciding, do not assume either answer.
- **2 are genuinely orphaned: ways 770850184 (250.9m from nearest road, id 68499) and 1084686582
  (340.2m from nearest road, id 46681).** Their raw OSM lon/lat are unremarkable, inside the
  Ingolstadt extract. This distance is too large to be a matching-threshold problem -- something else
  is going on (dropped road segment during conversion? a genuinely isolated pedestrian path?).
  Investigate, don't just silently continue excluding them.

## PROMPT X

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/crosswalk-match-distance-v1-<date>.

TASK 1 (the evidenced, safe fix): raise crosswalk_writer.py's matching tolerance to recover the 18
near-miss crossings (5.01m-14.53m from their true nearest road, all independently verified
unambiguous -- see context above). Don't just bump DEFAULT_MAX_MATCH_DIST_M to a round number without
re-deriving the ambiguity check yourself first -- re-verify the top-2-nearest-road gap for all 18
directly against the pinned map before and after your change, and confirm the new default doesn't
pull in any of the 32 far-misses (16.67m+) as accidental false positives. Report the exact new
match count (expect 127 -> 145, 71% -> 81%, unless your own re-verification finds a reason to differ
-- if so, explain why).

TASK 2 (investigate, don't assume): for the 2 orphaned crossings (770850184 at 250.9m from road
68499, 1084686582 at 340.2m from road 46681) -- determine whether there is a `highway=*` way in the
OSM source near either crossing's location that never made it into the XODR road network (a real
conversion-coverage gap), or whether these are legitimately isolated pedestrian paths with no nearby
vehicular road (correctly out of scope, no fix needed). Report which, with the specific OSM way(s)
you checked to reach that conclusion. Do not attempt a fix for whichever case doesn't need one.

TASK 3 (characterize, lower priority): for the 32 far-misses (16.67m-41.81m), sample enough of them
(not just the 3 already spot-checked) to determine if they're the same class as Task 2's genuine
gaps, or a different, larger population of legitimately-out-of-scope crossings (e.g. crossings of
footways/cycleways that structurally never get an OpenDRIVE road representation in this pipeline).
Report the breakdown. Only implement a fix here if you find a clear, safe pattern -- a characterization
report is an acceptable outcome for this task if the population turns out to be heterogeneous or the
correct threshold for each isn't obvious.

Do NOT touch the 127 already-matched crossings' behavior, and do not weaken the ambiguity/ safety
posture of match_crossing_to_road for its other callers (there are none currently, but keep the
function's contract honest for future use).

End with:
TASK_1_MATCH_COUNT: <before> -> <after>, out of 179, AMBIGUITY_REVERIFIED: PASS | FAIL
TASK_2_ORPHANED_CROSSINGS: <finding per way, with evidence>
TASK_3_FAR_MISS_CHARACTERIZATION: <breakdown> | NOT_DONE (why)
MAP_OF_RECORD_ACCEPTANCE_DELTA: <diff summary or "no measurable change">
FULL_OFFLINE_TESTS: PASS | FAIL
```
