# Lane Count From OSM

This candidate changes only generated non-junction roads that have no driving
lanes yet. Directional OSM metadata is mapped as `lanes:forward` to right-side
OpenDRIVE lanes and `lanes:backward` to left-side lanes. A total `lanes` value
is split deterministically; absent metadata retains the historical one-per-side
fallback with confidence `0.0`.

Every generated driving lane receives `userData` keys for count source,
confidence, and total count. `LaneGenerator.ensure_lanes()` can also write the
same road/lane records to `LANE_PROVENANCE_REPORT.json`.

The focused OSM count fixture passes, as do the available lane-link and target
validation tests. Full repository verification is incomplete because this
sparse exact-base worktree omits the OSM metadata modules required by the
existing width-policy tests. No map-of-record or CARLA runtime work was done.
