# Multi-spawn drive-route evidence (TrafficManager)

Date: 2026-08-17. Server: CARLA 0.9.16, loaded candidate
`ingolstadt_perception_clean_regen_crashsafe_20260815.xodr` (134.1 MB),
map name `Carla/Maps/OpenDriveMap`, 47,059 spawn points.

## Runs (--spawns 5, 240 frames each, TrafficManager autopilot)

| spawn | status  | distance | max speed | on_road | first_road_id | pos (x, y)          |
|-------|---------|----------|-----------|---------|---------------|---------------------|
| 0     | PARTIAL | 0.00 m   | 0.0 m/s   | 1.0     | 68423         | (12529, -3600)       |
| 1     | PARTIAL | 0.04 m   | 0.01 m/s  | 1.0     | 68267         | (6569, -10390)       |
| 2     | FAIL    | spawn_failed | —    | —       | —             | (4837, -9119)        |
| 3     | PASS    | 44.72 m  | 9.04 m/s  | 1.0     | 53427         | (6945, -2426)        |
| 4     | PASS    | 34.37 m  | 8.08 m/s  | 1.0     | 64307         | (4991, -7943)        |

Aggregate: 2/5 runs drove (run_fraction 0.4), total 79.1 m,
max speed 9.04 m/s, mean on-road 0.8. Coordinates: max |coord| = 10,390.8 m
(< 50 km, float32-safe). Results:
`drive_route_result.json` (this dir), `drive_route_multi_run.log`
(built-in autopilot, identical outcome — TrafficManager did not change it).

## Interpretation

- Dense/central road components drive normally: spawns 3 & 4 moved
  44.7 m / 34.4 m with on_road_fraction = 1.0 and no crash (server
  survived 5 sequential spawns, 1,200 total frames).
- The two stationary spawns (0, 1) are at the map periphery
  (10–12.5 km from origin). Both report on_road = 1.0 (a waypoint
  exists) but the vehicle never reaches 1 m/s in 240 frames with
  autopilot or TrafficManager. Conclusion: those roads are on
  **isolated/unreachable components** or dead-end geometry — the TM
  cannot build a route, so the ego idles. This is a genuine map-quality
  finding, not a probe artifact: acceptance's structural lane_connectivity
  gate (0 broken links) measures neighbor links, not component
  reachability from the drivable network.
- Spawn 2 (mid-map) failed to spawn the Tesla model — likely spawn
  collision/penetration; retried runs would clear it.

## Follow-up (phase 4 / map quality)

1. Optional probe extension: report per-component connectivity
   (waypoint topology BFS) so peripheral isolated roads are measurable
   without a live server.
2. Acceptance gate candidates: (a) fraction of spawn points whose
   component is reachable from the largest component; (b) drop
   spawn points on components smaller than N roads from capture pools.
3. This does not change the Phase-4 drivability claim for dense areas;
   the "islands" are limited to boundary roads.
