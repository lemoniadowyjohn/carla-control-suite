# Codex — PROMPT EE: source-aware roundabout detection for V2 (real map has 0 candidates)

## Context

Your own PROMPT CC work (`feature/roundabout-v2-real-map-validation-v1-20260913`, merged into
`integration/session-batch1-20260912` at `6c7434d4`) ran `roundabout_v2` against the real pinned map
for the first time and correctly declined to wire it: `detect_candidates()` found **zero** candidates,
even though the source OSM has 135 ways tagged `junction=roundabout`. Your report
(`CC_ROUNDABOUT_V2_REAL_MAP_VALIDATION.md`) already root-caused this precisely: the detector
(`ultimate_pipeline/topology/roundabout_v2/core.py:89-105`) only fires on EITHER of two signals, and
this map's real geometry has neither.

Read `detect_candidates()` yourself to confirm this is still accurate (don't trust this summary without
checking), but as of this session:

```python
def _marker(road):  # EXACT_OSM path
    for node in road.findall(".//userData/*"):
        ...
        if values.get("junction") in {"roundabout", "circular"}:
            return True, node.get("way_id") or node.get("id")
    return False, None

def detect_candidates(root):
    ...
    marks = [_marker(roads[r]) for r in ids]
    ways = sorted(w for ok, w in marks if ok and w)
    if ways: out.append(Candidate(..., "EXACT_OSM", 1.0, ...)); continue
    curvy = sum(any(g.find("arc") is not None or g.find("spiral") is not None
                    for g in roads[r].findall("./planView/geometry")) for r in ids)
    if curvy >= 3: out.append(Candidate(..., "TOPOLOGY_HIGH", 0.8, ...))
```

Two independent findings from this same session explain why BOTH paths are dead on this map:

1. **`EXACT_OSM` path**: nothing anywhere in this pipeline ever writes a `<userData>` node with
   `junction="roundabout"`/`"circular"` onto a road. This marker mechanism has no producer.
2. **`TOPOLOGY_HIGH` path**: this session independently found (fixing `structure_scanner.py`'s
   curvature check, commit `b01d19c8`) that **22,311 of 32,267 roads (~69%) on this map are a single
   `paramPoly3` geometry with no `<arc>` or `<spiral>` element at all** — paramPoly3 is this pipeline's
   dominant real geometry encoding, not the exception. A junction whose approach roads are curved
   paramPoly3 segments (which, per that same finding, plenty are — real roundabout approaches ARE
   curved) will never reach `curvy >= 3` no matter how curved they actually are, because this check
   only recognizes two specific XML tag names.

This map has real spatial OSM correspondence infrastructure already proven this session:
`ultimate_pipeline/enrichment/osm_xodr_correspondence.py` (`build_metadata_associations()`,
`match_osm_way_to_xodr()`) does exactly the kind of "does this XODR road correspond to that OSM way"
matching a roundabout detector needs, already used live by `stage_04_enrichment.py` for turn-lane/speed
metadata. `domain_gap/intersection_classifier.py` also already has roundabout-tag-aware logic worth
checking before you build anything new — read it first, it may already do (or nearly do) half of what
you need.

## PROMPT EE

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912 at
or after 6c7434d4 (has roundabout_v2 + your CC validation work already merged). Isolated branch:
feature/roundabout-v2-source-aware-detection-v1-<date>.

TASK 1: survey what already exists before writing anything new. Read
ultimate_pipeline/enrichment/osm_xodr_correspondence.py in full (build_metadata_associations,
match_osm_way_to_xodr, build_correspondence) and ultimate_pipeline/domain_gap/intersection_classifier.py
-- confirm whether either already contains reusable roundabout-specific matching logic, or whether
you're extending general-purpose road correspondence for a new purpose. State plainly which.

TASK 2: design and implement a new detection path for detect_candidates() (or a clearly-separated
companion function -- your call, but justify it) that identifies a junction as a roundabout candidate
using REAL spatial correspondence to OSM junction=roundabout ways, not the existing marker/arc-or-spiral
heuristics (leave those two paths alone -- this is additive, not a replacement). This needs, at minimum:
extracting the 135 real junction=roundabout ways from the pinned OSM source
(campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm), spatially matching each
one to XODR roads/junctions using the same kind of position-based correspondence
osm_xodr_correspondence.py already does for other metadata (do not invent a parallel, less-rigorous
matching scheme), and producing a Candidate with clear confidence/reason provenance distinguishing this
new "OSM_SPATIAL" class from the existing EXACT_OSM/TOPOLOGY_HIGH ones. Handle the real, expected
messiness: an OSM roundabout way may correspond to a multi-junction cluster in the converted XODR (a
roundabout is rarely one single <junction>), ambiguous or low-confidence matches must be excluded or
flagged, not guessed -- fail closed, matching this whole session's convention (see
turn_restriction_audit's confidence classes for the pattern to follow).

TASK 3: run the new detection path against the real pinned map (a COPY, never the pinned file itself).
Report exactly how many of the 135 source OSM roundabouts now produce a candidate, with a clear
breakdown of matched / unmatched-and-why (e.g. genuinely absent from the converted graph, ambiguous
junction correspondence, spatial match below your confidence threshold). Do not force every one of the
135 to match -- report the honest number.

TASK 4: for the newly-detected candidates, run them through the EXISTING RoundaboutV2Reconstructor /
validator chain unchanged (do not modify reconstruction logic in this task -- that's out of scope; this
task is detection only). Report how many successfully reconstruct vs. get rejected by the existing
validator, and why. This tells you whether the reconstructor itself is ready for real candidates once
detection actually finds them, or whether it has its OWN untested-on-real-data gaps -- report honestly
either way, don't fix reconstructor bugs in this task unless they're one-line and you're certain, in
which case say so explicitly and separately from the detection work.

TASK 5: repeat this session's established before/after methodology (measure_candidate_acceptance.py,
full metric diff, not just roundabout-specific numbers) for whatever set of candidates make it all the
way through reconstruction. Investigate wiring into the live pipeline using the same advisory-first,
env-var-gated, default-off-unless-evidence-says-otherwise convention as
UP_ENABLE_JUNCTION_CONNECTOR_SNAP / UP_ENABLE_G6_LANE_COVERAGE_REPAIR -- wire it ONLY if Task 3/4/5
results are clean; otherwise report exactly what's not ready and leave it unwired, the same honest
disposition your own CC prompt already modeled.

TASK 6: run the full offline test suite. Do not promote anything to auto_map_of_record.

End with:
TASK_1_EXISTING_INFRA_SURVEY: <what osm_xodr_correspondence.py / intersection_classifier.py already provide>
TASK_2_DETECTION_PATH_BUILT: PASS | FAIL -- <design summary>
TASK_3_REAL_MAP_DETECTION_RESULTS: <matched>/<135> source roundabouts, with the unmatched breakdown
TASK_4_RECONSTRUCTION_RESULTS: <reconstructed> / <rejected, with reasons> of the newly-detected candidates
TASK_5_WIRING_DECISION: WIRED (advisory, default off) | NOT_WIRED (with the specific reason)
TASK_6_FULL_OFFLINE_TESTS: PASS | FAIL
MAP_OF_RECORD_MUTATED: NO
```
