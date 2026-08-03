# G2 — lane polynomial validation (local-s)

- run_id: `20260803T210000Z`
- verdict: **PHASE_G_POLYNOMIAL_VALIDATION_PASS**

## Metrics (evaluated at local-s, spacing 4.0 m)

| metric | value |
|---|---|
| width samples | 760671 |
| max individual lane width | 6.0655 m |
| max total road width | 48.0 m |
| width p50 / p90 / p95 / p99 | 6.0 / 6.0 / 6.0 / 6.0 m |
| width max | 6.0655 m |
| max width derivative | 0.21 m/m |
| max section-boundary width jump | 0.0 m |
| negative-width count | 0 |
| cross-section inversion count | 0 |
| roads outside governed envelope | 0 |

## Checks

- non_finite_coefficients: PASS
- negative_width_zero: PASS
- implausible_width_zero: PASS
- extreme_width_derivative_zero: PASS
- width_records_within_section: PASS
- no_overlapping_width_intervals: PASS
- no_width_gaps: PASS
- no_double_laneoffset: PASS
- no_cross_section_inversion: PASS
- no_left_right_ordering_inversion: PASS
- non_finite_border_zero: PASS
- non_finite_laneoffset_zero: PASS

Every width/border/laneOffset record is evaluated with local-s semantics: width_ds = road_s - laneSection.s - width.sOffset, border_ds = road_s - laneSection.s - border.sOffset, lane_offset_ds = road_s - laneOffset.s.  Extreme or negative widths are reported fail-closed with the responsible record — they are NEVER clamped silently.