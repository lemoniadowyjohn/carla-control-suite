# F6 — seam + grade repair across the map

- run_id: `20260803T170000Z`
- verdict: **F6_SEAM_REPAIR_PASS**
- blend length: 25.0 m
- snap tolerance: 2.0 m (seams within tolerance are repaired;
  over-tolerance seams are REPORTED, never forced)

## Seam repair stats

| metric | value |
|---|---|
| seams checked | 45632 |
| seams fixed (bounded) | 44910 |
| already consistent | 664 |
| over threshold (reported, not forced) | 57 |
| max seam delta | 3.730 m |
| over-threshold fraction | 0.0012 |

## Integrity

- F5 candidate untouched: True
- road count preserved: True
- planView geometry preserved: True

## Checks

- f5_candidate_untouched: PASS
- road_count_preserved: PASS
- planview_geometry_preserved: PASS
- seams_checked: PASS
- seams_fixed_bounded: PASS
- over_threshold_reported_not_forced: PASS
- residual_over_threshold_within_tolerance: PASS

Residual inter-road seams within 2 m are repaired with a C0/C1 quadratic blend over 25 m at the downstream road start.  Seams that exceed the tolerance are logged as warnings (fail-closed) and left untouched — no elevation is invented.  planView geometry, road lengths and links are byte-identical between the F5 and F6 candidates.