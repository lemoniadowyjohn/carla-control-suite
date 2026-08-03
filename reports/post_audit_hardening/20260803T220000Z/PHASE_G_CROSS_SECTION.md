# G3 — cross-section reconstruction

- run_id: `20260803T220000Z`
- verdict: **PHASE_G_CROSS_SECTION_PASS**

## Full-map reconstruction

| metric | value |
|---|---|
| roads audited | 32710 |
| cross-section samples | 338964 |
| total issues | 0 |
| roads with issues | 43 |
| max section-boundary jump | 0.0 m |
| drivable width p50 / p95 / max | 6.0 / 12.0 / 30.0 m |

## Checks

- all_vertices_finite: PASS
- no_lane_overlap_or_crossover: PASS
- no_self_intersecting_cross_section: PASS
- monotonic_lateral_offsets: PASS
- positive_drivable_width: PASS
- section_boundary_continuity: PASS
- sections_available: PASS

## Fixtures

- one_lane_one_way: PASS (22 samples)
- two_lane_bidirectional: PASS (22 samples)
- multi_lane_arterial: PASS (26 samples)
- lane_addition: PASS (32 samples)
- lane_drop: PASS (32 samples)
- turn_lane: PASS (22 samples)
- shoulder: PASS (22 samples)
- sidewalk: PASS (22 samples)
- bicycle_lane: PASS (22 samples)
- junction_approach: PASS (18 samples)
- roundabout_approach: PASS (14 samples)

Cross-sections are reconstructed from planView reference-line evaluation (line/arc/spiral/paramPoly3), the laneOffset polynomial, and cumulative lane widths with side sign.  Offline preview: `PHASE_G_CROSS_SECTION_PREVIEW.svg`.