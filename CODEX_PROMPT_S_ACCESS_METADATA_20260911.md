# Codex — PROMPT S: attach access-restriction metadata (policy decided: metadata-only)

## Context

The earlier osm-access-restrictions-v1-20260908 investigation (beb23924, status
CORRECTNESS_BUG_FOUND) confirmed: roads OSM explicitly tags `motor_vehicle=no` or `vehicle=no`
are generated as ordinary driving roads with zero restriction representation (9 confirmed
instances via exact geometric matching, e.g. way 201201936 "Adam-Smith-Straße", XODR roads 43115/47787,
maximum_mean_geometry_distance_m=0.015). It correctly stopped short of a fix and asked for a
policy decision before changing production generation.

**Policy decision (operator-approved, 2026-09-11): metadata only, no generation/routing behavior
change in this pass.** Attach userData restriction metadata so downstream consumers (routing,
scenario design, future CARLA-side filtering) can react, but do not exclude roads from driving-lane
generation and do not change connectivity/routing semantics -- that remains a separate, larger
decision for later if ever pursued.

## PROMPT S

```text
Repository: lemoniadowyjohn/carla-control-suite. Isolated branch: feature/osm-access-metadata-v1-<date>.

CONFIRMED (osm-access-restrictions-v1-20260908 investigation, beb23924): access/motor_vehicle/
vehicle/psv/bicycle OSM tags are correctly matched to XODR roads (via the spatial correspondence
engine) but the result is discarded -- xodr_restriction_userdata is empty for every matched road.
Concrete confirmed matches: access=agricultural (6), access=destination (16),
motor_vehicle=destination (22), motor_vehicle=no (6), vehicle=destination (28), vehicle=no (3).

TASK:
1. For every road matched to an OSM way carrying access/motor_vehicle/vehicle/psv tags (reuse
   the exact matching approach and thresholds the prior investigation already validated -- do not
   rebuild matching from scratch), attach userData to the road (or its driving lane(s), whichever
   is the more natural fit given how this codebase's other provenance metadata is attached --
   follow the GAP-001/019 lane_count_source pattern for consistency) recording: the OSM tag key,
   its value, and a confidence/source field, same provenance discipline as prior OSM-derived
   metadata this session.
2. This must be metadata-only: do not change which roads get driving lanes, do not change lane
   counts, do not change any routing/connectivity behavior, do not add a new hard-fail or even
   soft-warn gate in this pass. If you find yourself tempted to also filter/exclude roads, stop --
   that's explicitly out of scope, a separate decision for later.
3. Add a regression fixture proving the metadata round-trips correctly (a road with a known
   OSM access tag ends up with the correct userData, a road with no such tag gets none).
4. Run against the pinned map-of-record and report real counts: how many roads/lanes now carry
   access-restriction metadata, broken down by tag type.

End with:
METADATA_ATTACHED: PASS | FAIL
PINNED_MAP_COUNTS: <breakdown by tag type>
NO_BEHAVIOR_CHANGE_CONFIRMED: PASS | FAIL -- <how you verified this, e.g. road/lane counts identical before/after>
FULL_OFFLINE_TESTS: PASS | FAIL
```
