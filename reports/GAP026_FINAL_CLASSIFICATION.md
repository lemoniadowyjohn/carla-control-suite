# GAP-026 Independent Oracle - Final Classification

## Summary
- CHECKER_FALSE_POSITIVE_RATE: 0.0000 (0/2992 - oracle matches checker exactly)
- SEVERE_GEOMETRY_DEFECT_COUNT: 1131
- GAP026_FINAL_CLASSIFICATION: GEOMETRY_DEFECTS_REAL_NOT_CHECKER_BIAS

## Evidence
- Independent oracle implemented using TWO geometry authorities:
  1. ultimate_pipeline/geometry/opendrive_geometry_kernel.py
  2. opendrive_geometry model (primitives + evaluator)
- Both oracles produce IDENTICAL results to production checker (0 delta)
- Oracle does NOT import LaneLinkBuilder.sanitize_junction_lane_links for its logic

## Failure Distribution (23,529 total laneLinks checked)

### Distance Errors
- Pass (0-0.25m): 20,538 (87.3%)
- 0.25-0.5m: 1,721
- 0.5-1m: 146
- 1-3m: 292
- 3-10m: 809
- >10m: 23
- MAX: 14.0m

### Angle Errors
- Pass (0-12deg): 23,078 (98.1%)
- 12-30deg: 99
- 30-90deg: 159
- 90-180deg: 193
- MAX: 180.0deg

### Severe Defects (unique)
- Distance > 3m: 832
- Angle > 12deg: 451
- Both >3m AND >12deg: 152
- **Unique severe defects: 1131**

### Near-Threshold Cluster
- 0.25-1m AND 12-30deg: 84

## Conclusion
The checker is NOT biased - it correctly identifies real geometry defects in the generated map.
The 2,992 failures are genuine lane-link continuity defects from the generator, not false positives.

Required action: Fix generator geometry (upstream), NOT widen checker tolerance.
